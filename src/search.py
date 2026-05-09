"""
Search layer: turn an :class:`~indexer.Indexer` into answers for ``print`` and ``find``.

``print`` looks up a **single** token (same rules as :mod:`indexer`). ``find`` splits
the query into tokens and returns page URLs that contain **every** token (Boolean
AND). Missing tokens or an empty query yield empty results—no exceptions for
"not found" style cases.

**Ranking:** ``find`` uses TF-IDF over the AND-matched set and returns URLs in
descending score order. Ties are resolved alphabetically by URL for stable output.
Corpus size for IDF calls ``Indexer.corpus_document_count()`` on each query so
totals stay correct if the index is mutated in-process.
"""

# allows newer type hint styles to work on older Python versions
# Docs: https://peps.python.org/pep-0563/
from __future__ import annotations

# math.log() is used in the TF-IDF formula to compute IDF scores
# Docs: https://docs.python.org/3/library/math.html#math.log
import math

# used for type hints in function signatures
# Docs: https://docs.python.org/3/library/typing.html
from typing import Dict, List, Set, Tuple

# import the Indexer and the helper functions we need from our own indexer module
from indexer import Indexer, PagePosting, normalize_term, tokenize


def split_query_into_terms(user_query: str) -> List[str]:
    """
    Normalise CLI/search input into indexer tokens.

    Leading or trailing space, or a query that is only whitespace, yields no
    tokens. Punctuation follows the same rules as indexing (:func:`~indexer.tokenize`).
    """
    # if the query is blank or just spaces, return nothing
    # str.strip() — Docs: https://docs.python.org/3/library/stdtypes.html#str.strip
    if not user_query.strip():
        return []

    # normalize_term() strips whitespace and lowercases the query
    # tokenize() then splits it into words using the same rules as the indexer
    return tokenize(normalize_term(user_query))


class SearchService:
    """
    Thin façade over :class:`~indexer.Indexer` for command-style lookups.

    Keep ``print`` (single-term postings) separate from ``find`` (multi-term
    URL list) so :mod:`main` can wire the CLI without duplicating token rules.
    """

    def __init__(self, inverted: Indexer) -> None:
        # store the Indexer so our methods can look things up in it
        self._inverted = inverted

    def postings_for_print(self, raw_word: str) -> Dict[str, PagePosting]:
        """
        Postings for one word, as required by ``print <word>``.

        Unknown words return an empty mapping; the caller formats that for the user.
        """
        # hand the word straight to the Indexer which handles normalisation and lookup
        return self._inverted.get_postings_for_term(raw_word)

    def urls_for_find(self, raw_query: str) -> List[str]:
        """
        Backward-compatible URL-only view of ranked find results.
        """
        # strip the score from each (url, score) pair and just return the URLs
        # list comprehension — Docs: https://docs.python.org/3/tutorial/datastructures.html#list-comprehensions
        return [url for url, _score in self.scored_urls_for_find(raw_query)]

    def scored_urls_for_find(self, raw_query: str) -> List[Tuple[str, float]]:
        """
        URLs of pages that contain **all** query terms (AND).

        Empty or whitespace-only queries return ``[]``. If any term is absent
        from the index, the result is ``[]``. URLs are relevance-ranked by TF-IDF
        with a stable alphabetical tiebreak.
        """
        # split the query into individual words
        lookup_parts = split_query_into_terms(raw_query)

        # if the query had no words at all, return nothing
        if not lookup_parts:
            return []

        # remove duplicate words from the query while keeping the original order
        # a set checks for duplicates; a list keeps the order
        # Docs: https://docs.python.org/3/library/stdtypes.html#set
        unique_terms: List[str] = []
        seen_terms: Set[str] = set()
        for token in lookup_parts:
            if token in seen_terms:
                continue
            seen_terms.add(token)
            unique_terms.append(token)

        # start with all pages that contain the first query word
        first_piece = unique_terms[0]
        initial_hits = self._inverted.get_postings_for_term(first_piece)
        urls_still_valid = set(initial_hits.keys())

        # keep only the pages that also contain every other query word (AND logic)
        # &= keeps only items that appear in both sets
        # Docs: https://docs.python.org/3/library/stdtypes.html#frozenset.intersection_update
        for extra_piece in unique_terms[1:]:
            next_hits = self._inverted.get_postings_for_term(extra_piece)
            urls_still_valid &= set(next_hits.keys())
            # if there are no pages left, stop early
            if not urls_still_valid:
                return []

        # ask the Indexer how many pages are in the index right now
        # we do this on every query so the count stays correct if new pages were added
        docs_total = self._inverted.corpus_document_count()

        # start each matching page's score at zero
        scores: Dict[str, float] = {url: 0.0 for url in urls_still_valid}

        for term in unique_terms:
            # get the postings for this word so we can read per-page frequencies
            postings = self._inverted.get_postings_for_term(term)

            # how many pages in the index contain this word
            doc_freq = len(postings)

            # IDF (Inverse Document Frequency) — words that appear on fewer pages get a higher score
            # we use the smoothed version: log((N+1) / (df+1)) + 1
            # the +1 values prevent division by zero for very common or rare words
            # math.log() — Docs: https://docs.python.org/3/library/math.html#math.log
            idf = math.log((docs_total + 1.0) / (doc_freq + 1.0)) + 1.0

            for url in urls_still_valid:
                # TF (Term Frequency) — how many times this word appears on this page
                tf = float(postings[url].frequency)
                # add the TF-IDF score for this word to the page's total score
                scores[url] += tf * idf

        # sort pages by score from highest to lowest; use the URL as a tiebreaker
        # Docs: https://docs.python.org/3/library/functions.html#sorted
        ranked = sorted(urls_still_valid, key=lambda url: (-scores[url], url))

        # return each URL paired with its score
        return [(url, scores[url]) for url in ranked]