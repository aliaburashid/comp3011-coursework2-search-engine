"""
HTTP crawler for https://quotes.toscrape.com/ with a fixed politeness delay.

Fetches HTML, extracts visible text for indexing, and enqueues same-host
``http``/``https`` links discovered on each page. Failed requests are skipped
without stopping the whole crawl.

**Queue duplicates:** Breadth-first search may enqueue the same URL more than
once before it is first processed; de-duplication happens when a URL is popped
via the ``finished`` set. That trades a little memory for simpler code—fine at
this site's scale.

**Text extraction:** :func:`page_plain_text` prefers **quote body text** from
each ``div.quote span.text`` on this site; if none are found, it falls back to
whole-page visible text (minus scripts/styles).

**Politeness:** The delay runs before *every* HTTP attempt after the first,
including after failures—so spacing between outbound requests stays at least
``politeness_seconds``. That is a defensible reading of "between successive
requests."
"""

# allows newer type hint styles to work on older Python versions
# Docs: https://peps.python.org/pep-0563/
from __future__ import annotations

# used to pause the crawler between requests (the politeness delay)
# Docs: https://docs.python.org/3/library/time.html#time.sleep
import time

# deque is a queue we can efficiently add to on the right and remove from the left
# Docs: https://docs.python.org/3/library/collections.html#collections.deque
from collections import deque

# dataclass lets us create simple data classes without writing lots of boilerplate
# Docs: https://docs.python.org/3/library/dataclasses.html
from dataclasses import dataclass, field

# used for type hints in function signatures
# Docs: https://docs.python.org/3/library/typing.html
from typing import Deque, List, Optional, Set, Tuple

# urldefrag removes the #fragment from a URL
# urljoin turns a relative link like "/page/2/" into a full URL
# urlparse splits a URL into parts like scheme, hostname, and path
# Docs: https://docs.python.org/3/library/urllib.parse.html
from urllib.parse import urldefrag, urljoin, urlparse

# requests is the library we use to download web pages (recommended by the brief)
# Docs: https://docs.python-requests.org/en/latest/
import requests

# BeautifulSoup is the library we use to parse HTML (recommended by the brief)
# Docs: https://www.crummy.com/software/BeautifulSoup/bs4/doc/
from bs4 import BeautifulSoup

# the website we are crawling, as specified in the coursework brief
DEFAULT_START_URL = "https://quotes.toscrape.com/"

# we must wait at least 6 seconds between requests, as required by the brief
POLITENESS_SECONDS = 6.0

# if a page takes longer than 30 seconds to respond, we give up on that request
# Docs: https://docs.python-requests.org/en/latest/user/advanced/#timeouts
REQUEST_TIMEOUT_SECONDS = 30.0

# this is sent in the HTTP User-Agent header so the server knows who is crawling it
# Docs: https://docs.python-requests.org/en/latest/user/advanced/#session-objects
DEFAULT_USER_AGENT = "COMP3011-search-crawler/1.0 (+educational)"


def strip_url_fragment(url: str) -> str:
    """Drop ``#fragment`` so the same page is not queued twice."""
    # urldefrag returns two values: the URL without the fragment, and the fragment itself
    # we only need the URL part, so we ignore the second value with _
    # Docs: https://docs.python.org/3/library/urllib.parse.html#urllib.parse.urldefrag
    without_hash, _ = urldefrag(url)
    return without_hash


def hostname_matches(url: str, allowed_host: str) -> bool:
    # urlparse breaks the URL apart so we can check the scheme and hostname
    # Docs: https://docs.python.org/3/library/urllib.parse.html#urllib.parse.urlparse
    bits = urlparse(url)

    # only follow http and https links, not ftp or anything else
    if bits.scheme not in ("http", "https"):
        return False

    # compare hostnames in lowercase so capitalisation differences do not matter
    return bits.netloc.lower() == allowed_host.lower()


def _fallback_full_page_plain_text(soup: BeautifulSoup) -> str:
    """Strip scripts/styles then take all visible text (legacy whole-page path)."""
    # get_text() pulls out all the readable text from the page joined by newlines
    # Docs: https://www.crummy.com/software/BeautifulSoup/bs4/doc/#get-text
    chunks = soup.get_text("\n", strip=True)

    # remove blank lines so we get clean plain text
    return "\n".join(line for line in chunks.splitlines() if line)


def page_plain_text(html: str) -> str:
    """
    Text to index for quotes.toscrape.com.

    Prefer each quote's main body: ``div.quote span.text`` (site template), joined
    with blank lines—this cuts nav, tag sidebars, and duplicate chrome. If no
    quote blocks match (unusual page), fall back to visible document text.
    """
    # parse the HTML string into a tree we can search through
    # Docs: https://www.crummy.com/software/BeautifulSoup/bs4/doc/#installing-a-parser
    soup = BeautifulSoup(html, "html.parser")

    # remove <script>, <style>, and <noscript> tags so their content does not get indexed
    # decompose() deletes the tag and everything inside it
    # Docs: https://www.crummy.com/software/BeautifulSoup/bs4/doc/#decompose
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # quotes.toscrape.com: one span.text per quote card
    # select() finds elements using a CSS selector — here we look for span.text inside div.quote
    # Docs: https://www.crummy.com/software/BeautifulSoup/bs4/doc/#css-selectors
    quote_spans = soup.select("div.quote span.text")
    if quote_spans:
        bodies: List[str] = []
        for span in quote_spans:
            # get the visible text out of this quote span
            # Docs: https://www.crummy.com/software/BeautifulSoup/bs4/doc/#get-text
            chunk = span.get_text("\n", strip=True)
            if chunk:
                bodies.append(chunk)
        if bodies:
            # join all the quote texts together with a blank line between each
            return "\n\n".join(bodies)

    # if there were no quote spans on the page, fall back to all visible page text
    return _fallback_full_page_plain_text(soup)


def harvest_same_host_links(html: str, current_url: str, allowed_host: str) -> List[str]:
    """Absolute same-host links found in ``html``."""
    # parse the HTML so we can search for links
    # Docs: https://www.crummy.com/software/BeautifulSoup/bs4/doc/#find-all
    soup = BeautifulSoup(html, "html.parser")
    found: List[str] = []

    # find_all("a", href=True) returns every <a> tag that has an href attribute
    # Docs: https://www.crummy.com/software/BeautifulSoup/bs4/doc/#find-all
    for anchor in soup.find_all("a", href=True):
        # urljoin turns a relative href into a full URL based on the current page's URL
        # Docs: https://docs.python.org/3/library/urllib.parse.html#urllib.parse.urljoin
        absolute = strip_url_fragment(urljoin(current_url, anchor["href"]))

        # only keep the link if it points to the same website we are crawling
        if hostname_matches(absolute, allowed_host):
            found.append(absolute)
    return found


# @dataclass automatically creates __init__ and other methods from the class fields
# Docs: https://docs.python.org/3/library/dataclasses.html
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

    # field(default_factory=list) makes sure each instance gets its own separate list
    # Docs: https://docs.python.org/3/library/dataclasses.html#dataclasses.field
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
    # use the provided settings or fall back to the defaults
    cfg = settings or CrawlSettings()

    # use the provided session or create a new one for making HTTP requests
    # Docs: https://docs.python-requests.org/en/latest/user/advanced/#session-objects
    session = http_session or requests.Session()

    # set the User-Agent on the session if it has not been set already
    # Docs: https://docs.python-requests.org/en/latest/user/advanced/#session-objects
    session.headers.setdefault("User-Agent", cfg.user_agent)

    # use the provided state or create a fresh one to track how many pages succeeded or failed
    trail = state or CrawlSessionState()

    # get the hostname from the start URL so we can check links belong to the same site
    # Docs: https://docs.python.org/3/library/urllib.parse.html
    allowed_host = urlparse(cfg.start_url).netloc

    # strip any fragment from the start URL before queuing it
    seed = strip_url_fragment(cfg.start_url)

    # the queue holds URLs we still need to visit; deque lets us remove from the front cheaply
    # Docs: https://docs.python.org/3/library/collections.html#collections.deque
    queue: Deque[str] = deque([seed])

    # keeps track of URLs we have already visited so we do not fetch the same page twice
    # Docs: https://docs.python.org/3/library/stdtypes.html#set
    finished: Set[str] = set()

    # will hold the (url, plain_text) pairs we return at the end
    stored: List[Tuple[str, str]] = []

    # tracks how many HTTP requests we have made; used to skip the delay before the first request
    requests_before_this_attempt = 0

    while queue:
        # take the next URL from the front of the queue
        target = strip_url_fragment(queue.popleft())

        # skip this URL if we have already visited it
        if target in finished:
            continue

        # mark this URL as visited before we fetch it
        finished.add(target)

        # wait 6 seconds before every request except the very first one
        # time.sleep() — Docs: https://docs.python.org/3/library/time.html#time.sleep
        if requests_before_this_attempt > 0:
            time.sleep(cfg.politeness_seconds)

        try:
            # download the page using an HTTP GET request
            # Docs: https://docs.python-requests.org/en/latest/api/#requests.Session.get
            reply = session.get(target, timeout=cfg.request_timeout)
        except requests.RequestException:
            # the request failed (e.g. connection error or timeout), so record it and move on
            # Docs: https://docs.python-requests.org/en/latest/api/#requests.exceptions.RequestException
            trail.failed_urls.append(target)
            # still increment so the next request gets the politeness delay
            requests_before_this_attempt += 1
            continue

        # count this request so the next one gets a delay
        requests_before_this_attempt += 1

        # if the server did not return 200 OK, record it as failed and skip it
        if reply.status_code != 200:
            trail.failed_urls.append(target)
            continue

        # decide which text encoding to use; fall back to utf-8 if we cannot tell
        # Docs: https://docs.python-requests.org/en/latest/api/#requests.Response.encoding
        encoding = reply.encoding or getattr(reply, "apparent_encoding", None) or "utf-8"
        reply.encoding = encoding

        # .text gives us the page content decoded as a Python string
        # Docs: https://docs.python-requests.org/en/latest/api/#requests.Response.text
        html_payload = reply.text

        # pull the plain text we want to index out of the HTML
        text_body = page_plain_text(html_payload)

        # save this page's URL and text to return to the indexer
        stored.append((target, text_body))
        trail.pages_fetched += 1

        # find all links on this page and add any new same-host ones to the queue
        for nxt in harvest_same_host_links(html_payload, target, allowed_host):
            nxt_clean = strip_url_fragment(nxt)
            # only add URLs we have not visited yet
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
    # just calls crawl_quotes_site with the same arguments;
    # the different name makes it clearer in main.py what the result is used for
    return crawl_quotes_site(settings=settings, http_session=http_session, state=state)