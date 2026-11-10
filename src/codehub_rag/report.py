"""Shareable audit evidence without publishing the scraped website corpus."""

from __future__ import annotations

import json
from pathlib import Path

from .ingest import read_jsonl


def build_report(directory: Path) -> str:
    audit = json.loads((directory / "audit.json").read_text(encoding="utf-8"))
    crawl = json.loads((directory / "crawl.json").read_text(encoding="utf-8"))
    documents = read_jsonl(directory / "documents.jsonl")
    eligible = sum(doc["retrieval_eligible"] for doc in documents)
    errors = [*audit["errors"], *crawl["errors"]]
    measures = {
        "Sitemap URLs": audit["urls"],
        "Sitemap documents read (including indexes)": len(audit["sitemaps"]),
        "Sitemap inventory complete": audit["inventory_complete"],
        "Page URLs attempted": crawl["attempted"],
        "Sample crawl": crawl["sample"],
        "Link discovery enabled": crawl["link_discovery_enabled"],
        "Accepted canonical documents": len(documents),
        "Documents eligible for retrieval": eligible,
        "Chunks": crawl["chunks"],
        "HTTP/extraction errors": len(errors),
        "Skipped responses": len(crawl["skipped"]),
        "Remaining crawl queue": crawl["remaining_queue"],
        "Observed internal links outside sitemaps": crawl["links_outside_sitemap"],
    }
    lines = [
        "# Code.Hub site audit",
        "",
        f"Run: `{directory.name}`. Crawl finished at {crawl['completed_at']} (UTC).",
        "",
        "## Coverage",
        "",
        "| Measure | Result |",
        "| --- | ---: |",
        *(f"| {label} | {value} |" for label, value in measures.items()),
        "",
        "Coverage is limited to the configured public HTML scope and URLs visible in this run. "
        "A drained queue does not prove that every page on the website was found. "
        "PDFs, external domains, authenticated pages and JavaScript-rendered content are excluded.",
        "",
        "## Sitemap categories",
        "",
        "| Category | URLs |",
        "| --- | ---: |",
        *(f"| {key} | {count} |" for key, count in audit["categories"].items()),
        "",
        "Category counts may overlap when a URL belongs to multiple sitemaps.",
        "",
        "## Quality review",
        "",
        f"- Thin documents: {len(crawl['thin_documents'])}.",
        f"- Unstructured extraction fallbacks: {len(crawl['unstructured_fallbacks'])}.",
        "- Taxonomy pages remain in the audit and link graph, but produce no retrieval chunks.",
        "- Animated Bricks counters use explicit source targets instead of placeholder zeros.",
        "- Chunk lengths are whitespace word counts, not embedding-model token counts.",
        "",
    ]
    warnings = crawl.get("metadata_warnings", [])
    if warnings:
        lines += ["### Source metadata warnings", ""]
        for item in warnings[:15]:
            lines.append(f"- {item['url']}")
            lines.extend(f"  - {warning}" for warning in item["warnings"])
        if len(warnings) > 15:
            lines.append(
                f"- Further affected documents: {len(warnings) - 15}; see local crawl.json."
            )
        lines += [
            "",
            "Source values are preserved. Warnings need review; no silent date, status "
            "or salary correction is applied.",
            "",
        ]
    lines += ["## Errors and exclusions", ""]
    if not errors:
        lines.append("No recorded sitemap or page-fetch errors.")
    else:
        lines.extend(f"- {item['url']}: {item['error']}" for item in errors)
    if crawl["skipped"]:
        lines += ["", "Skipped responses:", ""]
        lines.extend(f"- {item['url']}: {item['reason']}" for item in crawl["skipped"])
    lines += [
        "",
        "## Reproducibility",
        "",
        f"- Extractor: `{crawl['extractor_version']}`.",
        f"- Chunker: `{crawl['chunker_version']}`.",
        f"- Corpus hash: `{crawl['corpus_hash']}`.",
        "- Local artifacts include source HTML, inventory, document versions and chunks.",
        "- Raw HTML and extracted website content are not included in this repository.",
        "",
        "Embeddings, BM25, hybrid retrieval, reranking and answer generation are separate "
        "milestones; this report does not establish their quality.",
        "",
        "Sources: [robots.txt](https://codehub.gr/robots.txt), "
        "[sitemaps](https://codehub.gr/sitemaps.xml), [website](https://codehub.gr/).",
        "",
    ]
    return "\n".join(lines)
