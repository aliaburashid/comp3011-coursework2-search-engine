"""
Search layer: turn an :class:`~indexer.Indexer` into answers for ``print`` and ``find``.

``print`` looks up a **single** token (same rules as :mod:`indexer`). ``find`` splits
the query into tokens and returns page URLs that contain **every** token (Boolean
AND). Missing tokens or an empty query yield empty results—no exceptions for
“not found” style cases.

**Ranking:** ``find`` uses TF-IDF over the AND-matched set and returns URLs in
descending score order. Ties are resolved alphabetically by URL for stable output.
"""

from __future__ import annotations

import math
from typing import Dict, List, Set, Tuple

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
        self._cached_document_count: int | None = None

    def postings_for_print(self, raw_word: str) -> Dict[str, PagePosting]:
        """
        Postings for one word, as required by ``print <word>``.

        Unknown words return an empty mapping; the caller formats that for the user.
        """
        return self._inverted.get_postings_for_term(raw_word)

    def urls_for_find(self, raw_query: str) -> List[str]:
        """
        Backward-compatible URL-only view of ranked find results.
        """
        return [url for url, _score in self.scored_urls_for_find(raw_query)]

    def scored_urls_for_find(self, raw_query: str) -> List[Tuple[str, float]]:
        """
        URLs of pages that contain **all** query terms (AND).

        Empty or whitespace-only queries return ``[]``. If any term is absent
        from the index, the result is ``[]``. URLs are relevance-ranked by TF-IDF
        with a stable alphabetical tiebreak.
        """
        lookup_parts = split_query_into_terms(raw_query)
        if not lookup_parts:
            return []

        unique_terms: List[str] = []
        seen_terms: Set[str] = set()
        for token in lookup_parts:
            if token in seen_terms:
                continue
            seen_terms.add(token)
            unique_terms.append(token)

        first_piece = unique_terms[0]
        initial_hits = self._inverted.get_postings_for_term(first_piece)
        urls_still_valid = set(initial_hits.keys())

        for extra_piece in unique_terms[1:]:
            next_hits = self._inverted.get_postings_for_term(extra_piece)
            urls_still_valid &= set(next_hits.keys())
            if not urls_still_valid:
                return []

        docs_total = self._document_count()
        scores: Dict[str, float] = {url: 0.0 for url in urls_still_valid}

        for term in unique_terms:
            postings = self._inverted.get_postings_for_term(term)
            doc_freq = len(postings)
            idf = math.log((docs_total + 1.0) / (doc_freq + 1.0)) + 1.0
            for url in urls_still_valid:
                tf = float(postings[url].frequency)
                scores[url] += tf * idf

        ranked = sorted(urls_still_valid, key=lambda url: (-scores[url], url))
        return [(url, scores[url]) for url in ranked]

    def _document_count(self) -> int:
        if self._cached_document_count is not None:
            return self._cached_document_count

        urls: Set[str] = set()
        for by_url in self._inverted.internal_map().values():
            urls.update(by_url.keys())
        self._cached_document_count = max(len(urls), 1)
        return self._cached_document_count
