"""Tests for :mod:`search` — print-style postings and ranked AND-based find."""

from __future__ import annotations

import pytest

from indexer import Indexer
from search import SearchService, split_query_into_terms


@pytest.fixture
def sample_index() -> Indexer:
    inverted = Indexer()
    inverted.add_document("http://a.example/page", "alpha beta gamma")
    inverted.add_document("http://b.example/page", "beta gamma delta")
    inverted.add_document("http://c.example/page", "alpha delta only")
    return inverted


@pytest.fixture
def search(sample_index: Indexer) -> SearchService:
    return SearchService(sample_index)


def test_split_query_empty_and_whitespace() -> None:
    assert split_query_into_terms("") == []
    assert split_query_into_terms("   ") == []
    assert split_query_into_terms("\n\t") == []


def test_split_query_tokenizes_like_indexer() -> None:
    assert split_query_into_terms("Good Friends!") == ["good", "friends"]
    assert split_query_into_terms("  mixed-CASE  ") == ["mixed", "case"]


def test_postings_for_print_delegates_to_indexer(search: SearchService) -> None:
    out = search.postings_for_print("alpha")
    assert "http://a.example/page" in out
    assert "http://c.example/page" in out
    assert out["http://a.example/page"].frequency == 1


def test_postings_for_print_unknown_word_empty(search: SearchService) -> None:
    assert search.postings_for_print("nope") == {}


def test_postings_for_print_case_insensitive(search: SearchService) -> None:
    lower = search.postings_for_print("beta")
    upper = search.postings_for_print("BETA")
    assert lower == upper


def test_find_single_term_lists_all_pages_with_term(search: SearchService) -> None:
    urls = search.urls_for_find("gamma")
    assert urls == [
        "http://a.example/page",
        "http://b.example/page",
    ]


def test_find_multi_term_is_and_intersection(search: SearchService) -> None:
    assert search.urls_for_find("alpha beta") == ["http://a.example/page"]
    assert search.urls_for_find("beta delta") == ["http://b.example/page"]


def test_find_empty_query_returns_nothing(search: SearchService) -> None:
    assert search.urls_for_find("") == []
    assert search.urls_for_find("   ") == []


def test_find_missing_term_returns_nothing(search: SearchService) -> None:
    assert search.urls_for_find("alpha nonexistent") == []
    assert search.urls_for_find("ghost") == []


def test_find_tie_breaks_stably_by_url(search: SearchService) -> None:
    inverted = Indexer()
    inverted.add_document("http://z.site/", "shared word")
    inverted.add_document("http://a.site/", "shared word")
    inverted.add_document("http://m.site/", "shared word")
    svc = SearchService(inverted)
    assert svc.urls_for_find("shared") == [
        "http://a.site/",
        "http://m.site/",
        "http://z.site/",
    ]


def test_find_tf_idf_ranks_higher_term_frequency_first() -> None:
    inverted = Indexer()
    inverted.add_document("http://a.site/", "alpha alpha beta")
    inverted.add_document("http://b.site/", "alpha beta")
    inverted.add_document("http://c.site/", "beta beta beta")
    svc = SearchService(inverted)
    assert svc.urls_for_find("alpha beta") == [
        "http://a.site/",
        "http://b.site/",
    ]


def test_scored_find_returns_score_and_url_in_rank_order() -> None:
    inverted = Indexer()
    inverted.add_document("http://a.site/", "alpha alpha beta")
    inverted.add_document("http://b.site/", "alpha beta")
    svc = SearchService(inverted)
    scored = svc.scored_urls_for_find("alpha beta")
    assert scored[0][0] == "http://a.site/"
    assert scored[1][0] == "http://b.site/"
    assert scored[0][1] > scored[1][1]


def test_find_case_insensitive(search: SearchService) -> None:
    assert search.urls_for_find("ALPHA Beta") == ["http://a.example/page"]


def test_find_punctuation_heavy_query_matches_plain_terms(search: SearchService) -> None:
    plain = search.urls_for_find("alpha beta")
    noisy = search.urls_for_find('  Alpha,,,  Beta!!!  ')
    assert noisy == plain == ["http://a.example/page"]


def test_find_repeated_terms_same_as_single_term(search: SearchService) -> None:
    once = search.urls_for_find("alpha")
    twice = search.urls_for_find("alpha alpha")
    assert twice == once


def test_postings_for_print_multiword_is_empty(search: SearchService) -> None:
    """``print`` is single-token only; phrase-shaped strings have no postings."""
    assert search.postings_for_print("good friends") == {}
