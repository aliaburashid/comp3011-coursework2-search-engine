"""Tests for :mod:`search` — print-style postings and ranked AND-based find."""

# allows newer type hint styles to work on older Python versions
# Docs: https://peps.python.org/pep-0563/
from __future__ import annotations

# pytest is the test framework we use to run all our tests
# Docs: https://docs.pytest.org/en/stable/
import pytest

# import the classes we are testing
from indexer import Indexer
from search import SearchService, split_query_into_terms


# pytest fixture: creates a sample index that multiple tests can reuse
# Docs: https://docs.pytest.org/en/stable/how-to/fixtures.html
@pytest.fixture
def sample_index() -> Indexer:
    inverted = Indexer()
    inverted.add_document("http://a.example/page", "alpha beta gamma")
    inverted.add_document("http://b.example/page", "beta gamma delta")
    inverted.add_document("http://c.example/page", "alpha delta only")
    return inverted


# pytest fixture: creates a SearchService using the sample_index fixture above
@pytest.fixture
def search(sample_index: Indexer) -> SearchService:
    return SearchService(sample_index)


def test_split_query_empty_and_whitespace() -> None:
    # empty or whitespace-only queries should return an empty list
    assert split_query_into_terms("") == []
    assert split_query_into_terms("   ") == []
    assert split_query_into_terms("\n\t") == []


def test_split_query_tokenizes_like_indexer() -> None:
    # punctuation should be stripped and words lowercased, same as the indexer
    assert split_query_into_terms("Good Friends!") == ["good", "friends"]
    # hyphens and mixed case should be handled too
    assert split_query_into_terms("  mixed-CASE  ") == ["mixed", "case"]


def test_postings_for_print_delegates_to_indexer(search: SearchService) -> None:
    out = search.postings_for_print("alpha")
    # "alpha" appears in page a and page c
    assert "http://a.example/page" in out
    assert "http://c.example/page" in out
    # it appears once on page a
    assert out["http://a.example/page"].frequency == 1


def test_postings_for_print_unknown_word_empty(search: SearchService) -> None:
    # a word that was never indexed should return an empty dict
    assert search.postings_for_print("nope") == {}


def test_postings_for_print_case_insensitive(search: SearchService) -> None:
    # looking up "beta" and "BETA" should give the same result
    lower = search.postings_for_print("beta")
    upper = search.postings_for_print("BETA")
    assert lower == upper


def test_find_single_term_lists_all_pages_with_term(search: SearchService) -> None:
    urls = search.urls_for_find("gamma")
    # "gamma" appears on pages a and b — both should be returned
    assert urls == [
        "http://a.example/page",
        "http://b.example/page",
    ]


def test_find_multi_term_is_and_intersection(search: SearchService) -> None:
    # only page a has both "alpha" and "beta"
    assert search.urls_for_find("alpha beta") == ["http://a.example/page"]
    # only page b has both "beta" and "delta"
    assert search.urls_for_find("beta delta") == ["http://b.example/page"]


def test_find_empty_query_returns_nothing(search: SearchService) -> None:
    # empty or whitespace query should return nothing
    assert search.urls_for_find("") == []
    assert search.urls_for_find("   ") == []


def test_find_missing_term_returns_nothing(search: SearchService) -> None:
    # if any query word is not in the index, the result should be empty
    assert search.urls_for_find("alpha nonexistent") == []
    assert search.urls_for_find("ghost") == []


def test_find_tie_breaks_stably_by_url(search: SearchService) -> None:
    # when all pages have the same score, results should be sorted alphabetically by URL
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
    # page a has "alpha" twice so it should rank higher than page b which has it once
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
    # page a should come first with a higher score
    assert scored[0][0] == "http://a.site/"
    assert scored[1][0] == "http://b.site/"
    # the first score should be higher than the second
    assert scored[0][1] > scored[1][1]


def test_find_case_insensitive(search: SearchService) -> None:
    # uppercase query terms should match the same pages as lowercase
    assert search.urls_for_find("ALPHA Beta") == ["http://a.example/page"]


def test_find_punctuation_heavy_query_matches_plain_terms(search: SearchService) -> None:
    # a query with lots of punctuation should produce the same results as a clean query
    plain = search.urls_for_find("alpha beta")
    noisy = search.urls_for_find('  Alpha,,,  Beta!!!  ')
    assert noisy == plain == ["http://a.example/page"]


def test_find_repeated_terms_same_as_single_term(search: SearchService) -> None:
    # repeating a word in the query should give the same results as typing it once
    once = search.urls_for_find("alpha")
    twice = search.urls_for_find("alpha alpha")
    assert twice == once


def test_postings_for_print_multiword_is_empty(search: SearchService) -> None:
    """``print`` is single-token only; phrase-shaped strings have no postings."""
    # print only works with a single word — a phrase should return empty
    assert search.postings_for_print("good friends") == {}


def test_find_after_index_grows_uses_updated_corpus_count() -> None:
    """IDF denominator must follow ``Indexer.corpus_document_count()`` after new documents are added."""
    inverted = Indexer()
    inverted.add_document("http://a/", "alpha beta")
    svc = SearchService(inverted)
    # corpus starts with one document
    assert inverted.corpus_document_count() == 1
    # run a search to make sure nothing is cached from this point
    svc.scored_urls_for_find("alpha beta")
    # add a second document to the index
    inverted.add_document("http://b/", "alpha beta gamma")
    # corpus should now report two documents
    assert inverted.corpus_document_count() == 2
    # the search should now return results from both documents
    scored = svc.scored_urls_for_find("alpha beta")
    assert len(scored) == 2