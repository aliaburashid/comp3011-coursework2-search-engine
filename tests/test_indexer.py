"""Tests for :mod:`indexer` — tokenization, postings, re-index, and persistence shape."""

from __future__ import annotations

import json

from indexer import Indexer, tokenize


def test_tokenize_is_lowercase() -> None:
    assert tokenize("Hello WORLD") == ["hello", "world"]
    assert tokenize("MiXeD CaSe") == ["mixed", "case"]


def test_tokenize_drops_punctuation() -> None:
    assert tokenize("Hello, world!!!") == ["hello", "world"]
    assert tokenize('Say "hello"…') == ["say", "hello"]
    assert tokenize("no-punctuation") == ["no", "punctuation"]


def test_tokenize_empty_and_whitespace_only() -> None:
    assert tokenize("") == []
    assert tokenize("  \n\t  ") == []


def test_repeated_words_increase_frequency_and_positions() -> None:
    ix = Indexer()
    url = "http://example.com/page"
    ix.add_document(url, "the cat sat the")
    posting = ix.get_postings_for_term("the")[url]
    assert posting.frequency == 2
    assert posting.positions == [0, 3]


def test_positions_match_token_indices() -> None:
    ix = Indexer()
    url = "http://a.test/"
    ix.add_document(url, "alpha beta gamma beta")
    assert ix.get_postings_for_term("alpha")[url].positions == [0]
    assert ix.get_postings_for_term("beta")[url].positions == [1, 3]
    assert ix.get_postings_for_term("gamma")[url].positions == [2]


def test_empty_text_no_terms_indexed() -> None:
    ix = Indexer()
    ix.add_document("http://empty/", "")
    ix.add_document("http://whitespace/", "   \n\t  ")
    assert len(ix) == 0
    assert not ix.get_postings_for_term("anything")
    assert list(ix.terms()) == []


def test_lookup_is_case_insensitive_for_indexed_words() -> None:
    ix = Indexer()
    ix.add_document("http://x/", "CamelCase WORD")
    assert ix.get_postings_for_term("camelcase")["http://x/"].frequency == 1
    assert ix.get_postings_for_term("WORD")["http://x/"].frequency == 1


def test_digit_tokens_are_indexed() -> None:
    ix = Indexer()
    url = "http://n/"
    ix.add_document(url, "quote 123 quote")
    assert ix.get_postings_for_term("123")[url].frequency == 1
    assert ix.get_postings_for_term("123")[url].positions == [1]
    assert ix.get_postings_for_term("quote")[url].frequency == 2


def test_get_postings_returns_copies_not_internal_references() -> None:
    ix = Indexer()
    url = "http://copy.test/"
    ix.add_document(url, "word word")
    postings = ix.get_postings_for_term("word")
    postings[url].positions.append(999)
    assert ix.get_postings_for_term("word")[url].positions == [0, 1]


def test_has_term() -> None:
    ix = Indexer()
    ix.add_document("http://h/", "alpha beta")
    assert ix.has_term("alpha") is True
    assert ix.has_term("ALPHA") is True
    assert ix.has_term("gamma") is False
    assert ix.has_term("alpha beta") is False


def test_reindex_same_url_replaces_old_postings() -> None:
    ix = Indexer()
    url = "http://same/"
    ix.add_document(url, "only cats here")
    assert "dogs" not in ix.internal_map()
    ix.add_document(url, "only dogs now")
    assert ix.get_postings_for_term("cats") == {}
    dogs = ix.get_postings_for_term("dogs")[url]
    assert dogs.frequency == 1
    assert dogs.positions == [1]


def test_to_serializable_round_trip_matches_postings() -> None:
    ix = Indexer()
    ix.add_document("http://p/", "loop pool")
    raw = ix.to_serializable()
    ix2 = Indexer()
    ix2.load_serializable(raw)
    for term in ("loop", "pool"):
        assert ix.get_postings_for_term(term) == ix2.get_postings_for_term(term)


def test_json_file_round_trip() -> None:
    """Simulate save/load via JSON (typical single-file index)."""
    ix = Indexer()
    ix.add_document("http://json/", "persist round trip")
    blob = json.dumps(ix.to_serializable())
    ix2 = Indexer()
    ix2.load_serializable(json.loads(blob))
    assert ix2.get_postings_for_term("persist")["http://json/"].frequency == 1


def test_posting_from_dict_coerces_types() -> None:
    p = Indexer.posting_from_dict({"frequency": "3", "positions": ["0", "2"]})
    assert p.frequency == 3
    assert p.positions == [0, 2]


def test_multiword_lookup_returns_empty_for_print_style_api() -> None:
    ix = Indexer()
    ix.add_document("http://m/", "good friends")
    assert ix.get_postings_for_term("good friends") == {}


def test_get_postings_for_blank_term_returns_empty() -> None:
    ix = Indexer()
    ix.add_document("http://x/", "word")
    assert ix.get_postings_for_term("") == {}
    assert ix.get_postings_for_term("   ") == {}


def test_posting_from_dict_non_list_positions_becomes_empty() -> None:
    p = Indexer.posting_from_dict({"frequency": 2, "positions": "not-a-list"})
    assert p.positions == []


def test_reindex_skips_stale_inner_when_empty() -> None:
    """Purge path when a listed term has no remaining postings dict (edge case)."""
    ix = Indexer()
    ix.add_document("http://x/", "only")
    ix._index["ghost"] = {}
    ix._url_terms["http://x/"] = {"only", "ghost"}
    ix.add_document("http://x/", "fresh text here")
    assert ix.get_postings_for_term("fresh")
