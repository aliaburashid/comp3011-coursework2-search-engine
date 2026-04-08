"""
Search layer: turn an :class:`~indexer.Indexer` into answers for ``print`` and ``find``.

``print`` looks up a **single** token (same rules as :mod:`indexer`). ``find`` splits
the query into tokens and returns page URLs that contain **every** token (Boolean
AND). Missing tokens or an empty query yield empty results—no exceptions for
“not found” style cases.

**Ranking:** matches are **not** relevance-scored; URLs are returned sorted for
stable output. That meets the core brief. A later improvement (e.g. TF-IDF or
BM25 using term frequencies from the index) could replace alphabetical ordering
if you add an advanced-feature track.
"""

from __future__ import annotations

from typing import Dict, List

from indexer import Indexer, PagePosting, normalize_term, tokenize


def split_query_into_terms(user_query: str) -> List[str]:
    """
    Normalise CLI/search input into indexer tokens.

    Leading or trailing space, or a query that is only whitespace, yields no
    tokens. Punctuation follows the same rules as indexing (:func:`~indexer.tokenize`).
    """
    if not user_query.strip():
        return []
    return tokenize(normalize_term(user_query))


class SearchService:
    """
    Thin façade over :class:`~indexer.Indexer` for command-style lookups.

    Keep ``print`` (single-term postings) separate from ``find`` (multi-term
    URL list) so :mod:`main` can wire the CLI without duplicating token rules.
    """

    def __init__(self, inverted: Indexer) -> None:
        self._inverted = inverted

    def postings_for_print(self, raw_word: str) -> Dict[str, PagePosting]:
        """
        Postings for one word, as required by ``print <word>``.

        Unknown words return an empty mapping; the caller formats that for the user.
        """
        return self._inverted.get_postings_for_term(raw_word)

    def urls_for_find(self, raw_query: str) -> List[str]:
        """
        URLs of pages that contain **all** query terms (AND).

        Empty or whitespace-only queries return ``[]``. If any term is absent
        from the index, the result is ``[]``. URLs are sorted for stable,
        repeatable output.
        """
        lookup_parts = split_query_into_terms(raw_query)
        if not lookup_parts:
            return []

        first_piece = lookup_parts[0]
        initial_hits = self._inverted.get_postings_for_term(first_piece)
        urls_still_valid = set(initial_hits.keys())

        for extra_piece in lookup_parts[1:]:
            next_hits = self._inverted.get_postings_for_term(extra_piece)
            urls_still_valid &= set(next_hits.keys())
            if not urls_still_valid:
                return []

        return sorted(urls_still_valid)
