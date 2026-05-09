"""Tests for :mod:`crawler` — parsing helpers (no live network by default)."""

# allows newer type hint styles to work on older Python versions
# Docs: https://peps.python.org/pep-0563/
from __future__ import annotations

# Mock lets us replace real objects with fake ones in tests
# patch temporarily replaces a name in a module during a test
# Docs: https://docs.python.org/3/library/unittest.mock.html
from unittest.mock import Mock, patch

# imported so we can simulate a requests error in tests
# Docs: https://docs.python-requests.org/en/latest/api/#requests.exceptions.RequestException
import requests

# import everything we want to test from the crawler module
from crawler import (
    CrawlSessionState,
    CrawlSettings,
    crawl_quotes_site,
    crawl_to_indexer_payload,
    harvest_same_host_links,
    hostname_matches,
    page_plain_text,
    strip_url_fragment,
)


def test_strip_url_fragment_removes_hash() -> None:
    # check that the #top fragment is removed from the URL
    assert strip_url_fragment("https://quotes.toscrape.com/page/1/#top") == (
        "https://quotes.toscrape.com/page/1/"
    )


def test_hostname_matches_only_target_host() -> None:
    host = "quotes.toscrape.com"
    # same-site https link should match
    assert hostname_matches("https://quotes.toscrape.com/tag/wisdom/", host) is True
    # same-site http link should also match
    assert hostname_matches("http://quotes.toscrape.com/", host) is True
    # a different website should not match
    assert hostname_matches("https://evil.example/page", host) is False
    # ftp links should be rejected even if the hostname matches
    assert hostname_matches("ftp://quotes.toscrape.com/file", host) is False


def test_page_plain_text_drops_script_and_styles() -> None:
    html = """
    <html><head><style>.x{color:red}</style></head>
    <body>Hello<script>alert(1)</script><p>World</p></body></html>
    """
    text = page_plain_text(html)
    # javascript code inside <script> should not appear in the output
    assert "alert" not in text
    # css inside <style> should not appear in the output
    assert "color" not in text
    # normal visible text should still be there
    assert "Hello" in text
    assert "World" in text


def test_page_plain_text_prefers_quote_bodies_on_quotes_site() -> None:
    html = """
    <html><body>
    <nav>Home Next Login</nav>
    <div class="quote"><span class="text">"First quote body."</span></div>
    <footer>Copyright noise</footer>
    </body></html>
    """
    text = page_plain_text(html)
    # the quote text should be extracted
    assert "First quote body" in text
    # navigation text should be ignored when quote spans are present
    assert "Home Next Login" not in text
    # footer text should also be ignored
    assert "Copyright noise" not in text


def test_page_plain_text_joins_multiple_quotes() -> None:
    html = """
    <div class="quote"><span class="text">Alpha wisdom.</span></div>
    <div class="quote"><span class="text">Beta truth.</span></div>
    """
    text = page_plain_text(html)
    # both quotes should appear in the output
    assert "Alpha wisdom" in text
    assert "Beta truth" in text
    # the first quote should come before the second in the result
    assert text.index("Alpha") < text.index("Beta")


def test_harvest_same_host_links_resolves_relative() -> None:
    html = """
    <a href="/page/2/">next</a>
    <a href="https://quotes.toscrape.com/author/Albert-Einstein/">author</a>
    <a href="https://google.com/">offsite</a>
    """
    links = harvest_same_host_links(
        html,
        "https://quotes.toscrape.com/page/1/",
        "quotes.toscrape.com",
    )
    # the relative link should be resolved to a full URL and included
    assert "https://quotes.toscrape.com/page/2/" in links
    # the absolute same-host link should be included
    assert "https://quotes.toscrape.com/author/Albert-Einstein/" in links
    # the offsite link should not be included
    assert all("google.com" not in u for u in links)


def _ok_response(body: str) -> Mock:
    # helper that creates a fake successful HTTP response with status 200
    # Mock() creates a fake object we can configure however we like
    # Docs: https://docs.python.org/3/library/unittest.mock.html#unittest.mock.Mock
    reply = Mock()
    reply.status_code = 200
    reply.text = body
    reply.encoding = "utf-8"
    return reply


# @patch replaces time.sleep in the crawler module so tests don't actually wait 6 seconds
# Docs: https://docs.python.org/3/library/unittest.mock.html#unittest.mock.patch
@patch("crawler.time.sleep")
def test_crawl_waits_between_successive_requests(mock_sleep: Mock) -> None:
    session = Mock()
    first_page = """
    <html><body>
    <a href="/page/2/">next</a>
    visible one
    </body></html>
    """
    second_page = "<html><body>visible two</body></html>"
    # side_effect makes the mock return different values on successive calls
    # Docs: https://docs.python.org/3/library/unittest.mock.html#unittest.mock.Mock.side_effect
    session.get.side_effect = [_ok_response(first_page), _ok_response(second_page)]

    cfg = CrawlSettings(
        start_url="https://quotes.toscrape.com/",
        politeness_seconds=6.0,
    )
    rows = crawl_quotes_site(settings=cfg, http_session=session)

    # both pages should have been fetched
    assert len(rows) == 2
    # sleep should have been called exactly once (between the two requests)
    mock_sleep.assert_called_once_with(6.0)


@patch("crawler.time.sleep")
def test_single_page_no_sleep(mock_sleep: Mock) -> None:
    session = Mock()
    session.get.return_value = _ok_response("<html><body>only</body></html>")
    cfg = CrawlSettings(start_url="https://quotes.toscrape.com/")
    crawl_quotes_site(settings=cfg, http_session=session)
    # only one page means no delay should have been applied
    mock_sleep.assert_not_called()


@patch("crawler.time.sleep")
def test_network_error_recorded_and_crawl_continues(mock_sleep: Mock) -> None:
    session = Mock()
    first = _ok_response(
        """
    <html><body>
    <a href="https://quotes.toscrape.com/page/2/">next</a>
    home
    </body></html>
    """
    )
    # the second request raises a network error
    session.get.side_effect = [first, requests.RequestException("boom")]
    trail = CrawlSessionState()
    cfg = CrawlSettings(start_url="https://quotes.toscrape.com/")
    out = crawl_quotes_site(settings=cfg, http_session=session, state=trail)

    # the first page should still have been stored
    assert len(out) == 1
    assert "home" in out[0][1]
    # the failed URL should have been recorded
    assert trail.failed_urls == ["https://quotes.toscrape.com/page/2/"]


@patch("crawler.time.sleep")
def test_non_200_recorded_as_failed(mock_sleep: Mock) -> None:
    session = Mock()
    seed_html = """
    <html><body>
    <a href="https://quotes.toscrape.com/a/">a</a>
    <a href="https://quotes.toscrape.com/b/">b</a>
    </body></html>
    """
    # simulate a 500 server error for the first link
    bad = Mock()
    bad.status_code = 500
    bad.text = ""
    good_b = _ok_response("<html><body>bee</body></html>")
    session.get.side_effect = [
        _ok_response(seed_html),
        bad,
        good_b,
    ]
    trail = CrawlSessionState()
    cfg = CrawlSettings(start_url="https://quotes.toscrape.com/")
    out = crawl_quotes_site(settings=cfg, http_session=session, state=trail)
    # the URL that returned 500 should be in the failed list
    assert trail.failed_urls == ["https://quotes.toscrape.com/a/"]
    # the seed and the successful page should both be in the results
    assert len(out) == 2
    assert "bee" in out[1][1]


@patch("crawler.time.sleep")
def test_pages_fetched_matches_successful_responses(mock_sleep: Mock) -> None:
    session = Mock()
    p1 = '<html><body><a href="https://quotes.toscrape.com/p2/">x</a>one</body></html>'
    p2 = "<html><body>two</body></html>"
    session.get.side_effect = [_ok_response(p1), _ok_response(p2)]
    trail = CrawlSessionState()
    cfg = CrawlSettings(start_url="https://quotes.toscrape.com/")
    rows = crawl_quotes_site(settings=cfg, http_session=session, state=trail)
    # two pages fetched means two rows returned
    assert len(rows) == 2
    # pages_fetched should count both successful requests
    assert trail.pages_fetched == 2


@patch("crawler.time.sleep")
def test_pages_fetched_unchanged_when_request_fails(mock_sleep: Mock) -> None:
    session = Mock()
    # the only request raises an error
    session.get.side_effect = [requests.RequestException("nope")]
    trail = CrawlSessionState()
    crawl_quotes_site(settings=CrawlSettings(), http_session=session, state=trail)
    # no pages were successfully fetched
    assert trail.pages_fetched == 0


@patch("crawler.time.sleep")
def test_duplicate_links_on_page_do_not_duplicate_stored_rows(mock_sleep: Mock) -> None:
    """Same href twice still yields one fetch and one stored row for that URL."""
    session = Mock()
    seed = """
    <html><body>
    <a href="https://quotes.toscrape.com/shared/">first</a>
    <a href="https://quotes.toscrape.com/shared/">second</a>
    seed text
    </body></html>
    """
    shared = "<html><body>shared body</body></html>"
    session.get.side_effect = [_ok_response(seed), _ok_response(shared)]
    rows = crawl_quotes_site(settings=CrawlSettings(), http_session=session)
    urls = [u for u, _ in rows]
    # the shared URL should only appear once even though it was linked twice
    assert urls.count("https://quotes.toscrape.com/shared/") == 1
    # there should be exactly two rows: seed + shared
    assert len(rows) == 2


def test_crawl_to_indexer_payload_matches_crawl_quotes_site() -> None:
    # check that crawl_to_indexer_payload returns the same result as crawl_quotes_site
    session = Mock()
    session.get.return_value = _ok_response("<html><body>solo</body></html>")
    cfg = CrawlSettings(start_url="https://quotes.toscrape.com/")
    with patch("crawler.time.sleep"):
        direct = crawl_quotes_site(settings=cfg, http_session=session)
    session = Mock()
    session.get.return_value = _ok_response("<html><body>solo</body></html>")
    with patch("crawler.time.sleep"):
        alias = crawl_to_indexer_payload(settings=cfg, http_session=session)
    # both functions should return identical results
    assert alias == direct