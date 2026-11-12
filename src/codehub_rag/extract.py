"""HTML extraction and section-aware chunks; no embedding API required."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from .web import Resource, site_url

EXTRACTOR_VERSION = "html-v4"
CHUNKER_VERSION = "sections-v2"
BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr", "blockquote", "pre", "dt", "dd"}
UI_TEXT = re.compile(
    r"^(?:learn more|apply(?: now)?|share link|ready to apply\??|"
    r"see all (?:courses|trainings|open roles)|back to all (?:courses|trainings|roles)|"
    r"hot (?:course|position)|~3 minutes.*)$",
    re.I,
)


def trim_recommendations(root: Tag) -> None:
    """Recommendations belong to other entities, never to this page's subject."""
    marker = root.find(string=re.compile(r"^\s*Recommended for you\s*$", re.I))
    if marker is None:
        return
    current = marker
    while current is not root:
        for sibling in list(current.next_siblings):
            sibling.extract()
        parent = current.parent
        if current is marker:
            current.extract()
        current = parent


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def content_events(node):
    """Preserve orphan div/span text and inline markup without duplicating parents."""
    if isinstance(node, Comment):
        return
    if isinstance(node, NavigableString):
        if text := clean(str(node)):
            yield "text", text
    elif isinstance(node, Tag):
        if re.fullmatch(r"h[1-6]", node.name):
            yield node.name, clean(node.get_text(" ", strip=True))
        elif not node.find(list(BLOCK_TAGS)):
            if text := clean(node.get_text(" ", strip=True)):
                yield "text", text
        else:
            for child in node.children:
                yield from content_events(child)


def metadata_warnings(structured: list, visible_text: str) -> list[str]:
    warnings = []
    date_fields = {"startDate", "endDate", "datePosted", "validThrough"}

    def visit(value, path):
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                if key in date_fields and isinstance(child, str):
                    try:
                        datetime.fromisoformat(child)
                    except ValueError:
                        warnings.append(f"Invalid source date at {child_path}: {child}")
                if (
                    key == "unitText"
                    and child == "YEAR"
                    and re.search(r"per month", visible_text, re.I)
                ):
                    warnings.append(
                        f"Salary unit conflicts with visible monthly amount: {child_path}"
                    )
                if (
                    key == "eventStatus"
                    and str(child).endswith("EventScheduled")
                    and re.search(r"\bCompleted\b", visible_text)
                ):
                    warnings.append(
                        f"Scheduled event conflicts with visible Completed label: {child_path}"
                    )
                visit(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(structured, "jsonld")
    return warnings


def extract(resource: Resource, categories: list[str]) -> dict:
    soup = BeautifulSoup(resource.body, "html.parser")
    canonical_tag = soup.find("link", rel="canonical")
    canonical = (
        site_url(str(canonical_tag.get("href", "")), resource.url, page=True)
        if canonical_tag
        else None
    )
    canonical = canonical or resource.url
    title = clean(soup.title.get_text(" ")) if soup.title else ""
    description_tag = soup.find("meta", attrs={"name": "description"})
    description = str(description_tag.get("content", "")) if description_tag else ""
    robots_meta = soup.find_all(
        "meta", attrs={"name": re.compile(r"^(robots|CodeHubRAGBot)$", re.I)}
    )
    directives = ",".join(str(meta.get("content", "")) for meta in robots_meta)
    directives += "," + resource.headers.get("x-robots-tag", "")
    noindex = bool(re.search(r"\b(noindex|none)\b", directives, re.I))
    structured = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            structured.append(json.loads(script.get_text()))
        except (ValueError, TypeError):
            continue
    html_tag = soup.find("html")
    language = str(html_tag.get("lang", "")) if html_tag else ""
    links = sorted(
        {
            url
            for a in soup.find_all("a", href=True)
            if (url := site_url(str(a["href"]), resource.url, page=True))
        }
    )
    contact_blocks = []
    if urlsplit(canonical).path.rstrip("/") == "/contact":
        for anchor in soup.select("footer a[href], #brx-footer a[href]"):
            href = str(anchor.get("href", ""))
            value = ""
            if href.startswith("mailto:"):
                value = "Email: " + href[7:].split("?", 1)[0]
            elif href.startswith("tel:"):
                value = "Phone: " + href[4:]
            elif urlsplit(href).hostname in {
                "www.google.com",
                "maps.google.com",
                "maps.app.goo.gl",
            }:
                label = "Office address"
                # Preserve the location label from the same footer block; never
                # label a training-centre address as the headquarters.
                for parent in anchor.parents:
                    if parent.name == "footer" or parent.get("id") == "brx-footer":
                        break
                    labels = [
                        clean(p.get_text(" ", strip=True))
                        for p in parent.find_all(["p", "h2", "h3", "h4"])
                        if re.search(r"\b(center|centre|office|headquarters)\b", p.get_text(), re.I)
                    ]
                    if labels:
                        label = labels[0]
                        break
                value = label + ": " + clean(anchor.get_text(" ", strip=True))
            if value and value not in contact_blocks:
                contact_blocks.append(value)
    resolved_counters = []
    for counter in soup.select("[data-bricks-counter-options]"):
        try:
            options = json.loads(counter["data-bricks-counter-options"])
            target = str(options["countTo"])
            count_node = counter.select_one(".count")
            if count_node and re.fullmatch(r"\d+(?:\.\d+)?", target):
                count_node.string = target
                resolved_counters.append(
                    {"source_attribute": "data-bricks-counter-options", "value": target}
                )
        except (ValueError, TypeError, KeyError):
            continue
    root = soup.select_one("main") or soup.select_one("article") or soup.body or soup
    primary = root.find("h1")
    if primary:
        title = clean(primary.get_text(" ", strip=True)) or title
    if urlsplit(canonical).path.startswith(("/job/", "/course/", "/training/")):
        trim_recommendations(root)
    used_fallback = root.name not in {"main", "article"}
    for element in root.select(
        "script, style, nav, footer, aside, form, noscript, template, "
        "[hidden], [aria-hidden='true'], .cookie-banner, .cookie-notice, "
        ".cmplz-cookiebanner, .cky-consent-container, .breadcrumbs, .breadcrumb, "
        ".brxe-offcanvas, .floating-apply-bar, button"
    ):
        element.decompose()
    if used_fallback:
        for element in root.select("header"):
            element.decompose()
    for anchor in list(root.find_all("a")):
        if UI_TEXT.fullmatch(clean(anchor.get_text(" ", strip=True))):
            anchor.decompose()
    sections = []
    heading_stack: list[tuple[int, str]] = []
    current: dict = {"heading_path": [], "blocks": []}
    events = list(content_events(root))
    for kind, text in events:
        if not text or UI_TEXT.fullmatch(text):
            continue
        if re.fullmatch(r"h[1-6]", kind):
            if current["blocks"]:
                sections.append(current)
            level = int(kind[1])
            heading_stack = [(depth, text_) for depth, text_ in heading_stack if depth < level]
            heading_stack.append((level, text))
            current = {"heading_path": [text_ for _, text_ in heading_stack], "blocks": []}
        else:
            current["blocks"].append(text)
    if current["blocks"] or current["heading_path"]:
        sections.append(current)
    # Include standalone div/span text too: some page builders do not use paragraphs.
    full_text = clean(root.get_text(" ", strip=True))
    extracted_text = "\n\n".join(
        "\n".join([*section["heading_path"], *section["blocks"]]) for section in sections
    )
    structured_words = len(extracted_text.split())
    fallback = not sections or structured_words < len(full_text.split()) * 0.65
    if fallback:
        sections = [{"heading_path": [], "blocks": [full_text]}]
    text = "\n".join(text for _, text in events).strip() if not fallback else full_text
    if contact_blocks:
        heading = (
            "Published contact details: offices, training center, addresses, email and telephone"
        )
        sections.append({"heading_path": ["Contact Us", heading], "blocks": contact_blocks})
        text += "\n" + heading + "\n" + "\n".join(contact_blocks)
    content_hash = digest(
        json.dumps(
            {
                "text": text,
                "title": title,
                "description": description,
                "language": language,
                "structured_data": structured,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    page_id = digest(canonical)
    version_id = digest(f"{page_id}:{content_hash}:{EXTRACTOR_VERSION}")
    primary_categories = {"page", "post", "course", "training", "job", "link_discovery"}
    navigation_only = not bool(set(categories) & primary_categories) or urlsplit(
        canonical
    ).path.startswith(("/courses/", "/jobs/", "/trainings/", "/blog/category/"))
    return {
        "id": version_id,
        "page_id": page_id,
        "url": resource.url,
        "canonical_url": canonical,
        "title": title,
        "description": description,
        "language": language,
        "categories": categories,
        "text": text,
        "sections": sections,
        "links": links,
        "structured_data": structured,
        "content_hash": content_hash,
        "extractor_version": EXTRACTOR_VERSION,
        "fetched_at": datetime.now(UTC).isoformat(),
        "noindex": noindex,
        "retrieval_eligible": not noindex and not navigation_only and bool(text),
        "quality": {
            "word_count": len(text.split()),
            "body_fallback": used_fallback,
            "unstructured_fallback": fallback,
            "thin_content": len(text.split()) < 40,
            "metadata_warnings": metadata_warnings(structured, text),
            "navigation_only": navigation_only,
            "resolved_counters": resolved_counters,
        },
    }


def chunk(document: dict, max_words: int = 350, overlap: int = 45) -> list[dict]:
    if max_words < 1 or overlap < 0 or overlap >= max_words:
        raise ValueError("Require max_words > overlap >= 0")
    if not document["retrieval_eligible"]:
        return []
    chunks = []
    for section in document["sections"]:
        words = "\n".join(section["blocks"]).split()
        if not words or UI_TEXT.fullmatch(" ".join(words)):
            continue
        for start in range(0, len(words), max_words - overlap):
            body = " ".join(words[start : start + max_words])
            ordinal = len(chunks)
            context = " > ".join([document["title"], *section["heading_path"]])
            chunks.append(
                {
                    "id": digest(f"{document['id']}:{CHUNKER_VERSION}:{ordinal}:{body}"),
                    "document_version_id": document["id"],
                    "page_id": document["page_id"],
                    "ordinal": ordinal,
                    "url": document["canonical_url"],
                    "title": document["title"],
                    "heading_path": section["heading_path"],
                    "text": body,
                    "retrieval_text": context + "\n" + body,
                    "word_count": len(body.split()),
                    "chunker_version": CHUNKER_VERSION,
                }
            )
            if start + max_words >= len(words):
                break
    return chunks
