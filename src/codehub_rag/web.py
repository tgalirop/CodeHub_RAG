"""Bounded, sequential HTTP fetching with robots checks before every request."""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from protego import Protego

ORIGIN = "https://codehub.gr"
USER_AGENT = "CodeHubRAGBot/0.1 (+https://github.com/tgalirop/CodeHub_RAG)"
ROBOTS_AGENT = "CodeHubRAGBot"
MAX_BYTES = 8 * 1024 * 1024
ASSET_SUFFIXES = (
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".svg",
    ".webp",
    ".gif",
    ".zip",
    ".mp4",
    ".mp3",
    ".css",
    ".js",
    ".woff",
    ".woff2",
    ".xml",
    ".ico",
)


def site_url(value: str, base: str = ORIGIN + "/", *, page: bool = False) -> str | None:
    """Accept only public HTTPS URLs on the exact target host; remove tracking."""
    try:
        parts = urlsplit(urljoin(base, value.strip()))
        if (
            parts.scheme != "https"
            or parts.hostname not in {"codehub.gr", "www.codehub.gr"}
            or parts.port not in {None, 443}
            or parts.username
            or parts.password
        ):
            return None
        query = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in {"gclid", "fbclid"}
        ]
        path = parts.path or "/"
        if page and (query or path.lower().endswith(ASSET_SUFFIXES)):
            return None
        return urlunsplit(("https", "codehub.gr", path, urlencode(query), ""))
    except ValueError:
        return None


class FetchError(RuntimeError):
    pass


@dataclass
class Resource:
    url: str
    status: int
    body: bytes
    content_type: str
    headers: dict[str, str]

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class SiteClient:
    def __init__(self, delay: float = 0.8, *, transport: httpx.BaseTransport | None = None):
        self.delay = max(0, delay)
        self.last_request = 0.0
        self.policy: Protego | None = None
        self.requests = 0
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=20,
            follow_redirects=False,
            transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def allowed(self, url: str) -> bool:
        return self.policy is not None and self.policy.can_fetch(url, ROBOTS_AGENT)

    def load_robots(self) -> Resource:
        resource = self.fetch(ORIGIN + "/robots.txt", bootstrap=True)
        if resource.status == 404:
            self.policy = Protego.parse("")
        elif resource.status == 200:
            self.policy = Protego.parse(resource.text)
            crawl_delay = self.policy.crawl_delay(ROBOTS_AGENT)
            if crawl_delay is not None:
                self.delay = max(self.delay, float(crawl_delay))
        else:
            raise FetchError(f"Cannot establish robots policy: HTTP {resource.status}")
        return resource

    def fetch(self, url: str, *, bootstrap: bool = False) -> Resource:
        current = site_url(url)
        if current is None:
            raise FetchError(f"Out-of-scope URL: {url}")
        for _ in range(6):
            if not bootstrap and not self.allowed(current):
                raise FetchError(f"Robots disallow: {current}")
            resource = self._request(current)
            if resource.status in {301, 302, 303, 307, 308}:
                target = site_url(resource.headers.get("location", ""), current)
                if target is None or not resource.headers.get("location"):
                    raise FetchError(f"Blocked redirect from {current}")
                current = target
                continue
            return resource
        raise FetchError(f"Redirect limit: {url}")

    def _request(self, url: str) -> Resource:
        for attempt in range(3):
            time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            self.requests += 1
            try:
                with self.client.stream("GET", url) as response:
                    body = bytearray()
                    for part in response.iter_bytes():
                        body.extend(part)
                        if len(body) > MAX_BYTES:
                            raise FetchError(f"Response exceeds {MAX_BYTES} bytes: {url}")
                    resource = Resource(
                        str(response.url),
                        response.status_code,
                        bytes(body),
                        response.headers.get("content-type", "").lower(),
                        dict(response.headers),
                    )
            except httpx.HTTPError as error:
                if attempt == 2:
                    raise FetchError(f"HTTP request failed: {url}: {error}") from error
                time.sleep(2**attempt)
                continue
            if resource.status not in {429, 500, 502, 503, 504} or attempt == 2:
                return resource
            retry_after = resource.headers.get("retry-after", "")
            wait = (
                min(10, max(2**attempt, float(retry_after)))
                if retry_after.isdigit()
                else 2**attempt
            )
            time.sleep(wait)
        raise FetchError(f"Request failed: {url}")
