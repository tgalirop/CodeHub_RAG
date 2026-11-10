"""Sitemap inventory, bounded link discovery and reproducible ingestion artifacts."""

from __future__ import annotations

import json
from collections import Counter, deque
from datetime import UTC, datetime
from pathlib import Path

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from .extract import CHUNKER_VERSION, EXTRACTOR_VERSION, chunk, digest, extract
from .web import ORIGIN, FetchError, Resource, SiteClient, site_url


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, values: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def sitemap_entries(body: bytes) -> tuple[str, list[tuple[str, str | None]]]:
    root = ElementTree.fromstring(body)
    kind = root.tag.rsplit("}", 1)[-1]
    if kind not in {"sitemapindex", "urlset"}:
        raise ValueError(f"Unexpected XML root: {kind}")
    entries = []
    for element in root:
        fields = {child.tag.rsplit("}", 1)[-1]: child.text for child in element}
        if fields.get("loc"):
            entries.append((fields["loc"].strip(), fields.get("lastmod")))
    return kind, entries


def category_from_sitemap(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("-sitemap", 1)[0]


def inventory(client: SiteClient, directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    raw = directory / "raw"
    raw.mkdir()
    started = datetime.now(UTC).isoformat()
    robots = client.load_robots()
    (raw / "robots.txt").write_bytes(robots.body)
    roots = [url for value in client.policy.sitemaps if (url := site_url(value))]
    if not roots:
        roots = [ORIGIN + "/sitemaps.xml", ORIGIN + "/sitemap_index.xml", ORIGIN + "/sitemap.xml"]
    pending = deque((url, 0) for url in roots)
    seen = set()
    pages: dict[str, dict] = {}
    maps = []
    errors = []
    exclusions = []
    while pending:
        url, depth = pending.popleft()
        if url in seen:
            continue
        seen.add(url)
        print(f"Sitemap {len(seen)}: {url}", flush=True)
        try:
            if depth > 5 or len(seen) > 200:
                raise FetchError("Sitemap traversal limit reached")
            response = client.fetch(url)
            if response.status != 200:
                raise FetchError(f"HTTP {response.status}")
            kind, entries = sitemap_entries(response.body)
            (raw / f"sitemap-{digest(url)[:16]}.xml").write_bytes(response.body)
            maps.append({"url": url, "kind": kind, "entries": len(entries)})
            for value, lastmod in entries:
                target = site_url(value, url, page=kind == "urlset")
                if target is None:
                    exclusions.append({"url": value, "reason": "outside_scope_or_non_page"})
                elif kind == "sitemapindex":
                    pending.append((target, depth + 1))
                elif not client.allowed(target):
                    exclusions.append({"url": target, "reason": "robots"})
                else:
                    page = pages.setdefault(
                        target,
                        {
                            "url": target,
                            "categories": [],
                            "sitemaps": [],
                            "lastmod": lastmod,
                        },
                    )
                    category = category_from_sitemap(url)
                    if category not in page["categories"]:
                        page["categories"].append(category)
                    page["sitemaps"].append(url)
        except (FetchError, ValueError, ElementTree.ParseError, DefusedXmlException) as error:
            errors.append({"url": url, "error": str(error)})
    items = sorted(pages.values(), key=lambda item: item["url"])
    write_jsonl(directory / "inventory.jsonl", items)
    write_jsonl(directory / "exclusions.jsonl", exclusions)
    report = {
        "started_at": started,
        "completed_at": datetime.now(UTC).isoformat(),
        "origin": ORIGIN,
        "inventory_complete": not errors and bool(items),
        "sitemap_only": True,
        "urls": len(items),
        "sitemaps": maps,
        "categories": dict(sorted(Counter(c for p in items for c in p["categories"]).items())),
        "excluded": len(exclusions),
        "errors": errors,
        "http_requests": client.requests,
    }
    write_json(directory / "audit.json", report)
    return report


def sample_pages(pages: list[dict], limit: int) -> list[dict]:
    """Prioritize the homepage then round-robin through all sitemap categories."""
    groups: dict[str, deque] = {}
    priority = ["page", "job", "course", "training", "post"]
    for page in pages:
        groups.setdefault(
            page["categories"][0] if page["categories"] else "unknown", deque()
        ).append(page)
    selected = [page for page in pages if page["url"] == ORIGIN + "/"][:limit]
    seen = {page["url"] for page in selected}
    keys = sorted(
        groups, key=lambda key: (priority.index(key) if key in priority else len(priority), key)
    )
    while len(selected) < limit:
        before = len(selected)
        for key in keys:
            while groups[key] and groups[key][0]["url"] in seen:
                groups[key].popleft()
            if groups[key] and len(selected) < limit:
                page = groups[key].popleft()
                selected.append(page)
                seen.add(page["url"])
        if len(selected) == before:
            break
    return selected


def crawl(client: SiteClient, directory: Path, *, limit: int | None, discover: bool) -> dict:
    pages = read_jsonl(directory / "inventory.jsonl")
    if client.policy is None:
        client.load_robots()
    selected = sample_pages(pages, limit) if limit is not None else pages
    pending = deque(selected)
    queued = {page["url"] for page in selected}
    known = {page["url"] for page in pages}
    visited = set()
    canonical_seen = set()
    documents = []
    chunks = []
    errors = []
    skipped = []
    links = set()
    max_pages = limit if limit is not None else 10000
    while pending and len(visited) < max_pages:
        page = pending.popleft()
        url = page["url"]
        if url in visited:
            continue
        visited.add(url)
        print(f"Page {len(visited)}: {url}", flush=True)
        try:
            response = client.fetch(url)
            if response.status != 200:
                raise FetchError(f"HTTP {response.status}")
            if "text/html" not in response.content_type:
                skipped.append({"url": url, "reason": "non_html", "type": response.content_type})
                continue
            document = extract(response, page["categories"])
            raw_path = Path("raw") / f"page-{digest(url)[:20]}.html"
            (directory / raw_path).write_bytes(response.body)
            document["raw_path"] = raw_path.as_posix()
            document["response_headers"] = {
                key: value
                for key, value in response.headers.items()
                if key in {"content-type", "x-robots-tag", "etag", "last-modified"}
            }
            document["sitemap_lastmod"] = page.get("lastmod")
            links.update(document["links"])
            if discover:
                for link in document["links"]:
                    if link not in queued and client.allowed(link):
                        queued.add(link)
                        pending.append({"url": link, "categories": ["link_discovery"]})
            if document["noindex"]:
                skipped.append({"url": url, "reason": "noindex"})
                continue
            if document["canonical_url"] in canonical_seen:
                skipped.append({"url": url, "reason": "duplicate_canonical"})
                continue
            canonical_seen.add(document["canonical_url"])
            documents.append(document)
            chunks.extend(chunk(document))
        except FetchError as error:
            errors.append({"url": url, "error": str(error)})
    write_jsonl(directory / "documents.jsonl", documents)
    write_jsonl(directory / "chunks.jsonl", chunks)
    write_jsonl(
        directory / "discovered_links.jsonl",
        [
            {"url": url, "in_sitemap": url in known, "robots_allowed": client.allowed(url)}
            for url in sorted(links)
        ],
    )
    report = {
        "completed_at": datetime.now(UTC).isoformat(),
        "sample": limit is not None,
        "requested_limit": limit,
        "link_discovery_enabled": discover,
        "attempted": len(visited),
        "documents": len(documents),
        "chunks": len(chunks),
        "remaining_queue": len(pending),
        "crawl_complete": limit is None and not pending and not errors,
        "errors": errors,
        "skipped": skipped,
        "discovered_links": len(links),
        "links_outside_sitemap": len(links - known),
        **quality_report(documents, chunks),
    }
    write_json(directory / "crawl.json", report)
    return report


def quality_report(documents: list[dict], chunks: list[dict]) -> dict:
    return {
        "thin_documents": [doc["url"] for doc in documents if doc["quality"]["thin_content"]],
        "unstructured_fallbacks": [
            doc["url"] for doc in documents if doc["quality"]["unstructured_fallback"]
        ],
        "metadata_warnings": [
            {"url": doc["url"], "warnings": doc["quality"]["metadata_warnings"]}
            for doc in documents
            if doc["quality"]["metadata_warnings"]
        ],
        "navigation_documents_excluded_from_chunks": [
            doc["url"] for doc in documents if doc["quality"]["navigation_only"]
        ],
        "extractor_version": EXTRACTOR_VERSION,
        "chunker_version": CHUNKER_VERSION,
        "corpus_hash": digest("\n".join(sorted(item["id"] for item in chunks))),
    }


def reprocess(directory: Path) -> dict:
    """Re-extract previously accepted documents from raw HTML without network I/O."""
    previous = read_jsonl(directory / "documents.jsonl")
    documents = []
    chunks = []
    for old in previous:
        raw_path = (directory / old["raw_path"]).resolve()
        if not raw_path.is_relative_to(directory.resolve()):
            raise ValueError("Raw HTML path must stay inside the run directory")
        resource = Resource(
            old["url"],
            200,
            raw_path.read_bytes(),
            "text/html",
            old.get("response_headers", {}),
        )
        document = extract(resource, old["categories"])
        for key in ("raw_path", "fetched_at", "sitemap_lastmod", "response_headers"):
            if key in old:
                document[key] = old[key]
        if document["noindex"]:
            continue
        documents.append(document)
        chunks.extend(chunk(document))
    report = json.loads((directory / "crawl.json").read_text(encoding="utf-8"))
    report.update(
        {
            "reprocessed_at": datetime.now(UTC).isoformat(),
            "offline_reprocessing": True,
            "documents": len(documents),
            "chunks": len(chunks),
            **quality_report(documents, chunks),
        }
    )
    write_jsonl(directory / "documents.jsonl", documents)
    write_jsonl(directory / "chunks.jsonl", chunks)
    write_json(directory / "crawl.json", report)
    write_json(
        directory / "summary.json",
        {
            "run_directory": str(directory),
            "audit": json.loads((directory / "audit.json").read_text(encoding="utf-8")),
            "crawl": report,
        },
    )
    return report
