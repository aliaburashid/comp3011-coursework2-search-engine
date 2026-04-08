"""
Inverted index: maps canonical terms to per-page frequency and positions.

**Canonical terms** come from :func:`tokenize`: that function defines how raw
text becomes index keys (case, punctuation, splitting). Positions are 0-based
indices into the token sequence for that page, so repeated terms, phrase logic,
and ranking can use occurrence data later.

Token rule: ``[a-z0-9]+`` (see ``_TOKEN_RE``) — letters and digits are indexed
so numeric tokens are searchable; punctuation is dropped; hyphens split words
(e.g. ``co-op`` → ``co``, ``op``). Deliberate trade-off for English-heavy pages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Mapping, MutableMapping

# Index keys: contiguous ASCII letters/digits only (lowercased in tokenize).
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass
class PagePosting:
    """Statistics for one term on one page."""

    frequency: int = 0
    positions: List[int] = field(default_factory=list)

    def add_occurrence(self, position: int) -> None:
        self.frequency += 1
        self.positions.append(position)


# term (lowercase) -> url -> posting
InvertedIndexMap = MutableMapping[str, MutableMapping[str, PagePosting]]


def normalize_term(raw: str) -> str:
    """
    Light cleanup for user/CLI input before it is fed through :func:`tokenize`.

    This only strips and lowercases; it does **not** define index keys. All
    punctuation removal and splitting rules live in :func:`tokenize`, which is
    the single place terms are standardised for storage and lookup.
    """
    return raw.strip().lower()


def tokenize(text: str) -> List[str]:
    """
    Turn raw text into the canonical tokens used as inverted-index keys.

    This is the real normaliser: lowercasing, dropping non-alphanumerics, and
    splitting on anything that is not ``[a-z0-9]`` (so hyphens separate tokens).
    Empty input → ``[]``.
    """
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower())


class Indexer:
    """
    Build and query an inverted index.

    Calling ``add_document`` again for the same URL replaces that page's
    postings (re-crawl / refresh) without duplicating statistics.

    **Single-term lookups:** :meth:`get_postings_for_term` answers “where does
    this one token appear?” — aligned with the brief’s ``print <word>``.
    Multi-word and phrase queries are handled in ``search.py`` by combining
    per-term postings, not inside this class.
    """

    def __init__(self) -> None:
        self._index: Dict[str, Dict[str, PagePosting]] = {}
        self._url_terms: Dict[str, set[str]] = {}

    def clear(self) -> None:
        self._index.clear()
        self._url_terms.clear()

    def add_document(self, url: str, text: str) -> None:
        """Tokenize ``text`` and merge postings for ``url``."""
        if url in self._url_terms:
            self._purge_url(url)

        tokens = tokenize(text)
        if not tokens:
            self._url_terms[url] = set()
            return

        terms_seen: set[str] = set()
        for position, term in enumerate(tokens):
            terms_seen.add(term)
            by_url = self._index.setdefault(term, {})
            posting = by_url.setdefault(url, PagePosting())
            posting.add_occurrence(position)

        self._url_terms[url] = terms_seen

    def _purge_url(self, url: str) -> None:
        for term in self._url_terms.get(url, ()):
            by_url = self._index.get(term)
            if not by_url:
                continue
            by_url.pop(url, None)
            if not by_url:
                del self._index[term]
        self._url_terms.pop(url, None)

    def get_postings_for_term(self, term: str) -> Dict[str, PagePosting]:
        """
        Return postings for **one** indexable token (e.g. ``print nonsense``).

        Strings that :func:`tokenize` splits into multiple tokens (e.g. two
        words with a space) return no postings here — that is intentional:
        multi-word ``find`` behaviour belongs in the search layer, which can
        intersect postings per term. Single-token inputs still match
        case-insensitively (``Foo`` vs ``foo``) via :func:`tokenize`.
        """
        key = normalize_term(term)
        if not key:
            return {}
        tokens = tokenize(key)
        if len(tokens) != 1:
            return {}
        canonical = tokens[0]
        inner = self._index.get(canonical)
        if not inner:
            return {}
        return {u: PagePosting(p.frequency, list(p.positions)) for u, p in inner.items()}

    def has_term(self, term: str) -> bool:
        tokens = tokenize(normalize_term(term))
        if len(tokens) != 1:
            return False
        return tokens[0] in self._index

    def terms(self) -> Iterator[str]:
        return iter(sorted(self._index.keys()))

    def __len__(self) -> int:
        return len(self._index)

    def internal_map(self) -> Mapping[str, Mapping[str, PagePosting]]:
        """Read-only view of the underlying index (for persistence layers)."""
        return self._index

    @staticmethod
    def posting_to_dict(posting: PagePosting) -> Dict[str, object]:
        return {"frequency": posting.frequency, "positions": posting.positions}

    @staticmethod
    def posting_from_dict(data: Mapping[str, object]) -> PagePosting:
        freq = int(data.get("frequency", 0))
        pos = data.get("positions", [])
        if not isinstance(pos, list):
            pos = []
        positions = [int(p) for p in pos]
        return PagePosting(frequency=freq, positions=positions)

    def to_serializable(self) -> Dict[str, Dict[str, Dict[str, object]]]:
        """Nested dicts suitable for JSON/msgpack/etc."""
        out: Dict[str, Dict[str, Dict[str, object]]] = {}
        for term, by_url in self._index.items():
            out[term] = {
                url: Indexer.posting_to_dict(p) for url, p in by_url.items()
            }
        return out

    def load_serializable(self, data: Mapping[str, Mapping[str, Mapping[str, object]]]) -> None:
        """Replace this index from :meth:`to_serializable` output."""
        self.clear()
        for term, by_url in data.items():
            inner: Dict[str, PagePosting] = {}
            for url, payload in by_url.items():
                inner[url] = Indexer.posting_from_dict(payload)
            self._index[term] = inner
            for url in inner:
                self._url_terms.setdefault(url, set()).add(term)
