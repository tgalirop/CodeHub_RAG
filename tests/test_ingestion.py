import json

import httpx
import pytest
from defusedxml.common import DefusedXmlException

from codehub_rag.extract import chunk, extract
from codehub_rag.ingest import crawl, inventory, reprocess, sample_pages, sitemap_entries
from codehub_rag.report import build_report
from codehub_rag.web import FetchError, Resource, SiteClient, site_url

ROBOTS = """User-agent: *
Allow: /
Disallow: /private/
Disallow: /*?_
Sitemap: https://codehub.gr/sitemaps.xml
"""
HTML = """<html lang="en"><head><title>Code.Hub training</title>
<link rel="canonical" href="https://codehub.gr/course/test/">
<meta name="description" content="Training details">
<script type="application/ld+json">{"@type":"Course","name":"Test"}</script>
</head><body><header>OUTER MENU</header><main>
<nav>INNER MENU</nav><h1>Learn C#</h1><p>Build .NET applications with C#.</p>
<h2>Audience</h2><p>Software engineers and Java developers.</p>
<h2>Schedule</h2><table><tr><td>Monday</td><td>18:00</td></tr></table>
<a href="/another/">Another course</a><a href="https://external.test/">External</a>
<footer>FOOTER NOISE</footer></main></body></html>"""


def resource(html=HTML, headers=None):
    return Resource(
        "https://codehub.gr/course/test/", 200, html.encode(), "text/html", headers or {}
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/",
        "http://codehub.gr/",
        "https://codehub.gr.evil.test/",
        "https://codehub.gr:9999/",
        "https://name:pass@codehub.gr/",
        "//127.0.0.1/",
    ],
)
def test_scope_rejects_other_origins(url):
    assert site_url(url) is None


def test_page_urls_remove_tracking_but_reject_filters_and_assets():
    assert site_url("/course/?utm_source=test#details", page=True) == "https://codehub.gr/course/"
    assert site_url("/course/?_sort=title", page=True) is None
    assert site_url("/file.pdf", page=True) is None


def test_robots_wildcards_and_redirect_scope():
    requested = []

    def handler(request):
        requested.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        if request.url.path == "/redirect/":
            return httpx.Response(302, headers={"location": "https://evil.test/"})
        return httpx.Response(302, headers={"location": "/private/secret"})

    with SiteClient(0, transport=httpx.MockTransport(handler)) as client:
        client.load_robots()
        assert not client.allowed("https://codehub.gr/?_sort=title")
        with pytest.raises(FetchError, match="Blocked redirect"):
            client.fetch("https://codehub.gr/redirect/")
        with pytest.raises(FetchError, match="Robots disallow"):
            client.fetch("https://codehub.gr/allowed/")
    assert not any("secret" in url or "evil.test" in url for url in requested)


def test_robots_unavailable_fails_closed():
    with SiteClient(0, transport=httpx.MockTransport(lambda _: httpx.Response(403))) as client:
        with pytest.raises(FetchError, match="robots policy"):
            client.load_robots()
        assert not client.allowed("https://codehub.gr/")


def test_sitemap_ignores_image_locations_and_rejects_entities():
    body = b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
        <url><loc>https://codehub.gr/</loc><image:image><image:loc>BAD</image:loc>
        </image:image><lastmod>2026-11-01</lastmod></url></urlset>"""
    assert sitemap_entries(body) == ("urlset", [("https://codehub.gr/", "2026-11-01")])
    with pytest.raises(DefusedXmlException):
        sitemap_entries(
            b'<!DOCTYPE x [<!ENTITY a "oops">]><urlset><url><loc>&a;</loc></url></urlset>'
        )


def test_extraction_preserves_sections_tables_tech_terms_and_metadata():
    doc = extract(resource(), ["course"])
    assert "OUTER MENU" not in doc["text"]
    assert "INNER MENU" not in doc["text"]
    assert "FOOTER NOISE" not in doc["text"]
    assert "C#" in doc["text"] and ".NET" in doc["text"]
    assert "Monday 18:00" in doc["text"]
    assert doc["structured_data"][0]["@type"] == "Course"
    assert doc["language"] == "en"
    assert "https://codehub.gr/another/" in doc["links"]
    assert not any("external.test" in url for url in doc["links"])
    assert doc["sections"][1]["heading_path"] == ["Learn C#", "Audience"]


def test_stable_chunks_and_no_overlap_across_sections():
    doc = extract(resource(), ["course"])
    first = chunk(doc, max_words=5, overlap=1)
    assert first == chunk(doc, max_words=5, overlap=1)
    assert all(item["word_count"] <= 5 for item in first)
    assert len({item["id"] for item in first}) == len(first)
    assert all("Monday" not in item["text"] for item in first if "Audience" in item["heading_path"])
    changed = extract(resource(HTML.replace("Monday", "Tuesday")), ["course"])
    assert doc["id"] != changed["id"]


def test_page_builder_text_and_nested_list_labels_are_preserved():
    html = """<main><h1>Trainings</h1><div>Duration: <strong>6 hours</strong></div>
    <h2>Modules</h2><ul><li>Outer topic<ul><li>Inner topic</li></ul></li></ul>
    <div>Delivery: <span>Virtual</span></div></main>"""
    doc = extract(resource(html), ["course"])
    for text in ("Duration: 6 hours", "Outer topic", "Inner topic", "Delivery: Virtual"):
        assert text in doc["text"]
    assert not doc["quality"]["unstructured_fallback"]
    assert doc["text"].count("Inner topic") == 1


def test_html_comments_are_not_visible_source_content():
    html = "<main><!-- HIDDEN NOTE --><h1>Public</h1><p>Visible</p></main>"
    assert "HIDDEN NOTE" not in extract(resource(html), ["page"])["text"]


def test_retry_is_bounded_and_response_size_is_enforced(monkeypatch):
    monkeypatch.setattr("codehub_rag.web.time.sleep", lambda _: None)
    requested = []

    def handler(request):
        requested.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        return httpx.Response(503)

    with SiteClient(0, transport=httpx.MockTransport(handler)) as client:
        client.load_robots()
        assert client.fetch("https://codehub.gr/").status == 503
        assert len(requested) == 4
    monkeypatch.setattr("codehub_rag.web.MAX_BYTES", 32)
    with SiteClient(
        0, transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 33))
    ) as client:
        with pytest.raises(FetchError, match="Response exceeds"):
            client.load_robots()


def test_conflicting_source_metadata_is_flagged_without_silent_correction():
    html = """<script type="application/ld+json">{"@type":"Event",
    "startDate":"0207-20-26", "eventStatus":"https://schema.org/EventScheduled"}</script>
    <main><h1>AWS training</h1><p>Completed. Start date: 02/07/2026</p></main>"""
    doc = extract(resource(html), ["training"])
    assert len(doc["quality"]["metadata_warnings"]) == 2
    assert doc["structured_data"][0]["startDate"] == "0207-20-26"
    changed = extract(resource(html.replace("0207-20-26", "2026-07-02")), ["training"])
    assert changed["id"] != doc["id"]


def test_multiple_robots_meta_tags_use_restrictive_directive():
    html = """<head><meta name="robots" content="index, follow">
    <meta name="CodeHubRAGBot" content="noindex"></head><main><p>Content</p></main>"""
    assert extract(resource(html), ["page"])["noindex"]


def test_taxonomy_pages_are_kept_for_audit_but_excluded_from_chunks():
    doc = extract(resource(), ["course_language"])
    assert doc["text"]
    assert not doc["retrieval_eligible"]
    assert chunk(doc) == []


def test_counters_use_explicit_source_target_instead_of_animation_placeholder():
    html = """<main><h1>People</h1><h2>Specialists</h2><div
    data-bricks-counter-options='{"countFrom":0,"countTo":"300"}'>
    <span class="count">0</span><span>+</span></div></main>"""
    doc = extract(resource(html), ["page"])
    assert "300 +" in doc["text"]
    assert doc["quality"]["resolved_counters"][0]["value"] == "300"
    assert doc["text"].count("People") == 1


@pytest.mark.parametrize("directive", ["noindex", "none", "NOINDEX, follow"])
def test_noindex_never_becomes_chunks(directive):
    doc = extract(resource(headers={"x-robots-tag": directive}), ["course"])
    assert chunk(doc) == []


def test_sample_includes_homepage_and_primary_categories():
    pages = [{"url": "https://codehub.gr/", "categories": ["page"]}]
    pages += [
        {"url": f"https://codehub.gr/{kind}/{i}/", "categories": [kind]}
        for kind in ["page", "job", "course", "training", "post"]
        for i in range(10)
    ]
    selected = sample_pages(pages, 6)
    assert selected[0]["url"] == "https://codehub.gr/"
    assert {item["categories"][0] for item in selected} == {
        "page",
        "job",
        "course",
        "training",
        "post",
    }


def test_inventory_and_crawl_end_to_end(tmp_path):
    def handler(request):
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        if path == "/sitemaps.xml":
            return httpx.Response(
                200,
                text="""<sitemapindex><sitemap>
              <loc>https://codehub.gr/course-sitemap1.xml</loc></sitemap></sitemapindex>""",
            )
        if path == "/course-sitemap1.xml":
            return httpx.Response(
                200,
                text="""<urlset>
              <url><loc>https://codehub.gr/course/test/</loc></url>
              <url><loc>https://codehub.gr/course/test/</loc></url>
              <url><loc>https://codehub.gr/private/</loc></url>
              <url><loc>https://external.test/</loc></url></urlset>""",
            )
        return httpx.Response(200, text=HTML, headers={"content-type": "text/html"})

    directory = tmp_path / "run"
    with SiteClient(0, transport=httpx.MockTransport(handler)) as client:
        audit = inventory(client, directory)
        result = crawl(client, directory, limit=1, discover=False)
    assert audit["urls"] == 1 and audit["excluded"] == 2
    assert audit["inventory_complete"]
    assert result["documents"] == 1 and result["chunks"] > 0
    assert not result["errors"]
    assert list((directory / "raw").glob("page-*.html"))
    doc = json.loads((directory / "documents.jsonl").read_text(encoding="utf-8"))
    assert doc["raw_path"].endswith(".html")
    offline = reprocess(directory)
    assert offline["offline_reprocessing"]
    after = json.loads((directory / "documents.jsonl").read_text(encoding="utf-8"))
    assert after["id"] == doc["id"]
    assert after["fetched_at"] == doc["fetched_at"]
    summary = build_report(directory)
    assert "| Accepted canonical documents | 1 |" in summary
    assert "| Sample crawl | True |" in summary
    assert "PDFs, external domains" in summary


def test_failed_sitemap_marks_inventory_incomplete(tmp_path):
    def handler(request):
        return (
            httpx.Response(200, text=ROBOTS)
            if request.url.path == "/robots.txt"
            else httpx.Response(404)
        )

    with SiteClient(0, transport=httpx.MockTransport(handler)) as client:
        report = inventory(client, tmp_path / "run")
    assert not report["inventory_complete"]
    assert len(report["errors"]) == 1
