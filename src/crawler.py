"""
HTTP crawler for https://quotes.toscrape.com/ with a fixed politeness delay.

Fetches HTML, extracts visible text for indexing, and enqueues same-host
``http``/``https`` links discovered on each page. Failed requests are skipped
without stopping the whole crawl.

**Queue duplicates:** Breadth-first search may enqueue the same URL more than
once before it is first processed; de-duplication happens when a URL is popped
via the ``finished`` set. That trades a little memory for simpler code—fine at
this site’s scale.

**Text extraction:** :func:`page_plain_text` indexes broadly (whole document
minus scripts/styles). You could later restrict to main content only; not
required for the core brief.

**Politeness:** The delay runs before *every* HTTP attempt after the first,
including after failures—so spacing between outbound requests stays at least
``politeness_seconds``. That is a defensible reading of “between successive
requests.”
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Set, Tuple
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

DEFAULT_START_URL = "https://quotes.toscrape.com/"
POLITENESS_SECONDS = 6.0
REQUEST_TIMEOUT_SECONDS = 30.0
DEFAULT_USER_AGENT = "COMP3011-search-crawler/1.0 (+educational)"


def strip_url_fragment(url: str) -> str:
    """Drop ``#fragment`` so the same page is not queued twice."""
    without_hash, _ = urldefrag(url)
    return without_hash


def hostname_matches(url: str, allowed_host: str) -> bool:
    bits = urlparse(url)
    if bits.scheme not in ("http", "https"):
        return False
    return bits.netloc.lower() == allowed_host.lower()


def page_plain_text(html: str) -> str:
    """
    Visible text from the full HTML document (minus ``script``/``style`` noise).

    Whole-page text keeps the coursework simple; narrowing to quote/author
    regions only would be a refinement, not a requirement here.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    chunks = soup.get_text("\n", strip=True)
    return "\n".join(line for line in chunks.splitlines() if line)


def harvest_same_host_links(html: str, current_url: str, allowed_host: str) -> List[str]:
    """Absolute same-host links found in ``html``."""
    soup = BeautifulSoup(html, "html.parser")
    found: List[str] = []
    for anchor in soup.find_all("a", href=True):
        absolute = strip_url_fragment(urljoin(current_url, anchor["href"]))
        if hostname_matches(absolute, allowed_host):
            found.append(absolute)
    return found


@dataclass
class CrawlSettings:
    """Tunable crawl parameters (defaults match the coursework brief)."""

    start_url: str = DEFAULT_START_URL
    politeness_seconds: float = POLITENESS_SECONDS
    request_timeout: float = REQUEST_TIMEOUT_SECONDS
    user_agent: str = DEFAULT_USER_AGENT


@dataclass
class CrawlSessionState:
    """Book-keeping for one crawl run (used by tests and optional inspection)."""

    pages_fetched: int = 0
    failed_urls: List[str] = field(default_factory=list)


def crawl_quotes_site(
    settings: Optional[CrawlSettings] = None,
    http_session: Optional[requests.Session] = None,
    state: Optional[CrawlSessionState] = None,
) -> List[Tuple[str, str]]:
    """
    Breadth-first crawl starting at ``settings.start_url``.

    Waits **at least** ``settings.politeness_seconds`` before each HTTP GET
    **after the first attempt**—including attempts that raise or return non-200—
    so successive outbound requests stay spaced (see module docstring). Returns
    ``(url, plain_text)`` pairs in discovery order.
    """
    cfg = settings or CrawlSettings()
    session = http_session or requests.Session()
    session.headers.setdefault("User-Agent", cfg.user_agent)

    trail = state or CrawlSessionState()
    allowed_host = urlparse(cfg.start_url).netloc
    seed = strip_url_fragment(cfg.start_url)

    queue: Deque[str] = deque([seed])
    finished: Set[str] = set()
    stored: List[Tuple[str, str]] = []

    requests_before_this_attempt = 0

    while queue:
        target = strip_url_fragment(queue.popleft())
        if target in finished:
            continue
        finished.add(target)

        if requests_before_this_attempt > 0:
            time.sleep(cfg.politeness_seconds)

        try:
            reply = session.get(target, timeout=cfg.request_timeout)
        except requests.RequestException:
            trail.failed_urls.append(target)
            requests_before_this_attempt += 1
            continue

        requests_before_this_attempt += 1

        if reply.status_code != 200:
            trail.failed_urls.append(target)
            continue

        encoding = reply.encoding or getattr(reply, "apparent_encoding", None) or "utf-8"
        reply.encoding = encoding
        html_payload = reply.text
        text_body = page_plain_text(html_payload)
        stored.append((target, text_body))
        trail.pages_fetched += 1

        for nxt in harvest_same_host_links(html_payload, target, allowed_host):
            nxt_clean = strip_url_fragment(nxt)
            if nxt_clean not in finished:
                queue.append(nxt_clean)

    return stored


def crawl_to_indexer_payload(
    settings: Optional[CrawlSettings] = None,
    http_session: Optional[requests.Session] = None,
    state: Optional[CrawlSessionState] = None,
) -> List[Tuple[str, str]]:
    """
    Convenience alias: same return value as :func:`crawl_quotes_site`.

    Name makes the hand-off to :class:`~indexer.Indexer.add_document` obvious
    from :mod:`main`.
    """
    return crawl_quotes_site(settings=settings, http_session=http_session, state=state)
