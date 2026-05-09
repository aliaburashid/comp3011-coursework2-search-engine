"""Tests for :mod:`indexer` — tokenization, postings, re-index, and persistence shape."""

# allows newer type hint styles to work on older Python versions
# Docs: https://peps.python.org/pep-0563/
from __future__ import annotations

# json is used to simulate saving and loading the index as a file
# Docs: https://docs.python.org/3/library/json.html
import json

# import the classes and functions we are testing
from indexer import Indexer, tokenize


def test_tokenize_is_lowercase() -> None:
    # tokenize should always return lowercase tokens regardless of input case
    assert tokenize("Hello WORLD") == ["hello", "world"]
    assert tokenize("MiXeD CaSe") == ["mixed", "case"]


def test_tokenize_drops_punctuation() -> None:
    # commas and exclamation marks should be removed
    assert tokenize("Hello, world!!!") == ["hello", "world"]
    # unicode punctuation like curly quotes should also be removed
    assert tokenize('Say "hello"…') == ["say", "hello"]
    # hyphens should split words into separate tokens
    assert tokenize("no-punctuation") == ["no", "punctuation"]


def test_tokenize_splits_apostrophe_contractions() -> None:
    # apostrophes split words just like hyphens do — this is a known trade-off
    assert tokenize("don't") == ["don", "t"]
    assert tokenize("it's") == ["it", "s"]


def test_tokenize_empty_and_whitespace_only() -> None:
    # empty string should return an empty list
    assert tokenize("") == []
    # whitespace-only string should also return an empty list
    assert tokenize("  \n\t  ") == []


def test_repeated_words_increase_frequency_and_positions() -> None:
    ix = Indexer()
    url = "http://example.com/page"
    ix.add_document(url, "the cat sat the")
    posting = ix.get_postings_for_term("the")[url]
    # "the" appears twice so frequency should be 2
    assert posting.frequency == 2
    # "the" appears at positions 0 and 3 in the token stream
    assert posting.positions == [0, 3]


def test_positions_match_token_indices() -> None:
    ix = Indexer()
    url = "http://a.test/"
    ix.add_document(url, "alpha beta gamma beta")
    # "alpha" is the first token so it should be at position 0
    assert ix.get_postings_for_term("alpha")[url].positions == [0]
    # "beta" appears at positions 1 and 3
    assert ix.get_postings_for_term("beta")[url].positions == [1, 3]
    # "gamma" is at position 2
    assert ix.get_postings_for_term("gamma")[url].positions == [2]


def test_empty_text_no_terms_indexed() -> None:
    ix = Indexer()
    # pages with no text should add nothing to the index
    ix.add_document("http://empty/", "")
    ix.add_document("http://whitespace/", "   \n\t  ")
    # the index should have no terms
    assert len(ix) == 0
    assert not ix.get_postings_for_term("anything")
    assert list(ix.terms()) == []


def test_corpus_document_count_tracks_urls() -> None:
    ix = Indexer()
    # empty index should still return at least 1 to avoid division by zero in IDF
    assert ix.corpus_document_count() == 1
    ix.add_document("http://a/", "one")
    # one URL added so count should be 1
    assert ix.corpus_document_count() == 1
    ix.add_document("http://b/", "two")
    # two URLs now so count should be 2
    assert ix.corpus_document_count() == 2


def test_lookup_is_case_insensitive_for_indexed_words() -> None:
    ix = Indexer()
    ix.add_document("http://x/", "CamelCase WORD")
    # looking up in lowercase should find the word indexed from "CamelCase"
    assert ix.get_postings_for_term("camelcase")["http://x/"].frequency == 1
    # looking up in uppercase should also work
    assert ix.get_postings_for_term("WORD")["http://x/"].frequency == 1


def test_digit_tokens_are_indexed() -> None:
    ix = Indexer()
    url = "http://n/"
    ix.add_document(url, "quote 123 quote")
    # numbers should be indexed as tokens
    assert ix.get_postings_for_term("123")[url].frequency == 1
    assert ix.get_postings_for_term("123")[url].positions == [1]
    # "quote" appears twice
    assert ix.get_postings_for_term("quote")[url].frequency == 2


def test_get_postings_returns_copies_not_internal_references() -> None:
    ix = Indexer()
    url = "http://copy.test/"
    ix.add_document(url, "word word")
    postings = ix.get_postings_for_term("word")
    # modifying the returned posting should not change the internal index
    postings[url].positions.append(999)
    assert ix.get_postings_for_term("word")[url].positions == [0, 1]


def test_has_term() -> None:
    ix = Indexer()
    ix.add_document("http://h/", "alpha beta")
    # "alpha" was indexed so has_term should return True
    assert ix.has_term("alpha") is True
    # lookups should be case-insensitive
    assert ix.has_term("ALPHA") is True
    # "gamma" was never indexed
    assert ix.has_term("gamma") is False
    # multi-word input should return False — has_term only checks single tokens
    assert ix.has_term("alpha beta") is False


def test_reindex_same_url_replaces_old_postings() -> None:
    ix = Indexer()
    url = "http://same/"
    ix.add_document(url, "only cats here")
    # "dogs" was not in the first version of the page
    assert "dogs" not in ix.internal_map()
    # re-index the same URL with different content
    ix.add_document(url, "only dogs now")
    # "cats" should have been removed from the index
    assert ix.get_postings_for_term("cats") == {}
    # "dogs" should now be indexed
    dogs = ix.get_postings_for_term("dogs")[url]
    assert dogs.frequency == 1
    assert dogs.positions == [1]


def test_to_serializable_round_trip_matches_postings() -> None:
    ix = Indexer()
    ix.add_document("http://p/", "loop pool")
    # convert the index to a plain dict
    raw = ix.to_serializable()
    # load that dict into a brand new Indexer
    ix2 = Indexer()
    ix2.load_serializable(raw)
    # the postings in the new Indexer should match the original
    for term in ("loop", "pool"):
        assert ix.get_postings_for_term(term) == ix2.get_postings_for_term(term)


def test_json_file_round_trip() -> None:
    """Simulate save/load via JSON (typical single-file index)."""
    ix = Indexer()
    ix.add_document("http://json/", "persist round trip")
    # convert to JSON string and back, simulating writing to and reading from a file
    # Docs: https://docs.python.org/3/library/json.html
    blob = json.dumps(ix.to_serializable())
    ix2 = Indexer()
    ix2.load_serializable(json.loads(blob))
    # the reloaded index should contain the same postings
    assert ix2.get_postings_for_term("persist")["http://json/"].frequency == 1


def test_posting_from_dict_coerces_types() -> None:
    # frequency and positions might be stored as strings; posting_from_dict should handle that
    p = Indexer.posting_from_dict({"frequency": "3", "positions": ["0", "2"]})
    assert p.frequency == 3
    assert p.positions == [0, 2]


def test_multiword_lookup_returns_empty_for_print_style_api() -> None:
    ix = Indexer()
    ix.add_document("http://m/", "good friends")
    # get_postings_for_term only handles single words — two words should return empty
    assert ix.get_postings_for_term("good friends") == {}


def test_get_postings_for_blank_term_returns_empty() -> None:
    ix = Indexer()
    ix.add_document("http://x/", "word")
    # empty string should return empty
    assert ix.get_postings_for_term("") == {}
    # whitespace-only should also return empty
    assert ix.get_postings_for_term("   ") == {}


def test_posting_from_dict_non_list_positions_becomes_empty() -> None:
    # if positions is not a list (e.g. corrupted data), it should default to empty
    p = Indexer.posting_from_dict({"frequency": 2, "positions": "not-a-list"})
    assert p.positions == []


def test_reindex_skips_stale_inner_when_empty() -> None:
    """Purge path when a listed term has no remaining postings dict (edge case)."""
    ix = Indexer()
    ix.add_document("http://x/", "only")
    # manually inject a ghost entry to simulate a corrupted state
    ix._index["ghost"] = {}
    ix._url_terms["http://x/"] = {"only", "ghost"}
    # re-indexing should clean up the ghost entry without crashing
    ix.add_document("http://x/", "fresh text here")
    assert ix.get_postings_for_term("fresh")