"""Tests for :mod:`crawler` — parsing helpers (no live network by default)."""

from __future__ import annotations

from unittest.mock import Mock, patch

import requests

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
    assert strip_url_fragment("https://quotes.toscrape.com/page/1/#top") == (
        "https://quotes.toscrape.com/page/1/"
    )


def test_hostname_matches_only_target_host() -> None:
    host = "quotes.toscrape.com"
    assert hostname_matches("https://quotes.toscrape.com/tag/wisdom/", host) is True
    assert hostname_matches("http://quotes.toscrape.com/", host) is True
    assert hostname_matches("https://evil.example/page", host) is False
    assert hostname_matches("ftp://quotes.toscrape.com/file", host) is False


def test_page_plain_text_drops_script_and_styles() -> None:
    html = """
    <html><head><style>.x{color:red}</style></head>
    <body>Hello<script>alert(1)</script><p>World</p></body></html>
    """
    text = page_plain_text(html)
    assert "alert" not in text
    assert "color" not in text
    assert "Hello" in text
    assert "World" in text


def test_page_plain_text_prefers_quote_bodies_on_quotes_site() -> None:
    html = """
    <html><body>
    <nav>Home Next Login</nav>
    <div class="quote"><span class="text">“First quote body.”</span></div>
    <footer>Copyright noise</footer>
    </body></html>
    """
    text = page_plain_text(html)
    assert "First quote body" in text
    assert "Home Next Login" not in text
    assert "Copyright noise" not in text


def test_page_plain_text_joins_multiple_quotes() -> None:
    html = """
    <div class="quote"><span class="text">Alpha wisdom.</span></div>
    <div class="quote"><span class="text">Beta truth.</span></div>
    """
    text = page_plain_text(html)
    assert "Alpha wisdom" in text
    assert "Beta truth" in text
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
    assert "https://quotes.toscrape.com/page/2/" in links
    assert "https://quotes.toscrape.com/author/Albert-Einstein/" in links
    assert all("google.com" not in u for u in links)


def _ok_response(body: str) -> Mock:
    reply = Mock()
    reply.status_code = 200
    reply.text = body
    reply.encoding = "utf-8"
    return reply


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
    session.get.side_effect = [_ok_response(first_page), _ok_response(second_page)]

    cfg = CrawlSettings(
        start_url="https://quotes.toscrape.com/",
        politeness_seconds=6.0,
    )
    rows = crawl_quotes_site(settings=cfg, http_session=session)

    assert len(rows) == 2
    mock_sleep.assert_called_once_with(6.0)


@patch("crawler.time.sleep")
def test_single_page_no_sleep(mock_sleep: Mock) -> None:
    session = Mock()
    session.get.return_value = _ok_response("<html><body>only</body></html>")
    cfg = CrawlSettings(start_url="https://quotes.toscrape.com/")
    crawl_quotes_site(settings=cfg, http_session=session)
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
    session.get.side_effect = [first, requests.RequestException("boom")]
    trail = CrawlSessionState()
    cfg = CrawlSettings(start_url="https://quotes.toscrape.com/")
    out = crawl_quotes_site(settings=cfg, http_session=session, state=trail)

    assert len(out) == 1
    assert "home" in out[0][1]
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
    assert trail.failed_urls == ["https://quotes.toscrape.com/a/"]
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
    assert len(rows) == 2
    assert trail.pages_fetched == 2


@patch("crawler.time.sleep")
def test_pages_fetched_unchanged_when_request_fails(mock_sleep: Mock) -> None:
    session = Mock()
    session.get.side_effect = [requests.RequestException("nope")]
    trail = CrawlSessionState()
    crawl_quotes_site(settings=CrawlSettings(), http_session=session, state=trail)
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
    assert urls.count("https://quotes.toscrape.com/shared/") == 1
    assert len(rows) == 2


def test_crawl_to_indexer_payload_matches_crawl_quotes_site() -> None:
    session = Mock()
    session.get.return_value = _ok_response("<html><body>solo</body></html>")
    cfg = CrawlSettings(start_url="https://quotes.toscrape.com/")
    with patch("crawler.time.sleep"):
        direct = crawl_quotes_site(settings=cfg, http_session=session)
    session = Mock()
    session.get.return_value = _ok_response("<html><body>solo</body></html>")
    with patch("crawler.time.sleep"):
        alias = crawl_to_indexer_payload(settings=cfg, http_session=session)
    assert alias == direct
