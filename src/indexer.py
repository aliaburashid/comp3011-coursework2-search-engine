"""
Inverted index: maps canonical terms to per-page frequency and positions.

**Canonical terms** come from :func:`tokenize`: that function defines how raw
text becomes index keys (case, punctuation, splitting). Positions are 0-based
indices into the token sequence for that page, so repeated terms, phrase logic,
and ranking can use occurrence data later.

Token rule: ``[a-z0-9]+`` (see ``_TOKEN_RE``) — letters and digits are indexed
so numeric tokens are searchable; punctuation is dropped; anything outside
``[a-z0-9]`` splits tokens (e.g. ``co-op`` → ``co``, ``op``; ``don't`` → ``don``,
``t``; ``it's`` → ``it``, ``s``). Deliberate trade-off for English-heavy pages.
"""

# allows newer type hint styles to work on older Python versions
# Docs: https://peps.python.org/pep-0563/
from __future__ import annotations

# re lets us use regular expressions to find words in text
# Docs: https://docs.python.org/3/library/re.html
import re

# dataclass and field help us create simple data-storage classes with less code
# Docs: https://docs.python.org/3/library/dataclasses.html
from dataclasses import dataclass, field

# used for type hints in function signatures
# Docs: https://docs.python.org/3/library/typing.html
from typing import Dict, Iterator, List, Mapping, MutableMapping

# this pattern matches runs of letters and digits only (lowercase)
# anything else — spaces, hyphens, apostrophes, punctuation — acts as a word boundary
# re.compile() — Docs: https://docs.python.org/3/library/re.html#re.compile
_TOKEN_RE = re.compile(r"[a-z0-9]+")


# @dataclass automatically writes __init__ and other methods from the fields below
# Docs: https://docs.python.org/3/library/dataclasses.html
@dataclass
class PagePosting:
    """Statistics for one term on one page."""

    # how many times this term appears on the page
    frequency: int = 0

    # the position of each occurrence in the token stream (0-based)
    # field(default_factory=list) gives each instance its own list so they don't share one
    # Docs: https://docs.python.org/3/library/dataclasses.html#dataclasses.field
    positions: List[int] = field(default_factory=list)

    def add_occurrence(self, position: int) -> None:
        # add one to the count every time we see this term on the page
        self.frequency += 1
        # remember the position in the token stream where it appeared
        self.positions.append(position)


# type alias for the full index structure: term -> url -> PagePosting
# MutableMapping is a flexible dict-like type from the typing module
# Docs: https://docs.python.org/3/library/typing.html#typing.MutableMapping
InvertedIndexMap = MutableMapping[str, MutableMapping[str, PagePosting]]


def normalize_term(raw: str) -> str:
    """
    Light cleanup for user/CLI input before it is fed through :func:`tokenize`.

    This only strips and lowercases; it does **not** define index keys. All
    punctuation removal and splitting rules live in :func:`tokenize`, which is
    the single place terms are standardised for storage and lookup.
    """
    # strip() removes spaces from both ends; lower() converts to lowercase
    # Docs: https://docs.python.org/3/library/stdtypes.html#str.strip
    return raw.strip().lower()


def tokenize(text: str) -> List[str]:
    """
    Turn raw text into the canonical tokens used as inverted-index keys.

    This is the real normaliser: lowercasing, dropping non-alphanumerics, and
    splitting on anything that is not ``[a-z0-9]`` (hyphens, apostrophes, etc.).
    Empty input → ``[]``.
    """
    # return an empty list straight away if the input is empty or None
    if not text:
        return []

    # findall() finds every sequence of letters/digits in the lowercased text
    # this also handles splitting on hyphens, apostrophes, and all other punctuation
    # Docs: https://docs.python.org/3/library/re.html#re.Pattern.findall
    return _TOKEN_RE.findall(text.lower())


class Indexer:
    """
    Build and query an inverted index.

    Calling ``add_document`` again for the same URL replaces that page's
    postings (re-crawl / refresh) without duplicating statistics.

    **Single-term lookups:** :meth:`get_postings_for_term` answers "where does
    this one token appear?" — aligned with the brief's ``print <word>``.
    Multi-word and phrase queries are handled in ``search.py`` by combining
    per-term postings, not inside this class.
    """

    def __init__(self) -> None:
        # the main index: maps each word to a dict of {url: PagePosting}
        # using a plain dict gives fast lookups by word
        # Docs: https://docs.python.org/3/library/stdtypes.html#dict
        self._index: Dict[str, Dict[str, PagePosting]] = {}

        # keeps track of which words each URL added to the index
        # this lets us quickly remove a URL's entries when we re-index it
        self._url_terms: Dict[str, set[str]] = {}

    def clear(self) -> None:
        # remove everything from both dicts without creating new objects
        # Docs: https://docs.python.org/3/library/stdtypes.html#dict.clear
        self._index.clear()
        self._url_terms.clear()

    def add_document(self, url: str, text: str) -> None:
        """Tokenize ``text`` and merge postings for ``url``."""
        # if we have seen this URL before, remove its old data first
        if url in self._url_terms:
            self._purge_url(url)

        # split the page text into words
        tokens = tokenize(text)

        # if the page has no words at all, still record the URL so it counts towards the corpus size
        if not tokens:
            self._url_terms[url] = set()
            return

        # remember which words this URL contributes so we can remove them later if needed
        terms_seen: set[str] = set()

        # enumerate() gives us both the position and the word at that position
        # Docs: https://docs.python.org/3/library/functions.html#enumerate
        for position, term in enumerate(tokens):
            terms_seen.add(term)

            # setdefault() gets the existing dict for this word, or creates an empty one
            # Docs: https://docs.python.org/3/library/stdtypes.html#dict.setdefault
            by_url = self._index.setdefault(term, {})
            posting = by_url.setdefault(url, PagePosting())

            # record this occurrence of the word
            posting.add_occurrence(position)

        # save the set of words this URL contributed
        self._url_terms[url] = terms_seen

    def _purge_url(self, url: str) -> None:
        # go through every word this URL contributed
        for term in self._url_terms.get(url, ()):
            by_url = self._index.get(term)
            # skip if the word's entry has already been removed
            if not by_url:
                continue

            # remove this URL from the word's postings dict
            # Docs: https://docs.python.org/3/library/stdtypes.html#dict.pop
            by_url.pop(url, None)

            # if no URLs remain for this word, remove the word from the index entirely
            if not by_url:
                del self._index[term]

        # remove the URL from our reverse lookup map
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
        # clean up the input before looking it up
        key = normalize_term(term)

        # return empty straight away if the input was blank
        if not key:
            return {}

        # tokenize the cleaned input to check it is exactly one word
        tokens = tokenize(key)

        # if the input contained more than one word, this method does not handle it
        if len(tokens) != 1:
            return {}

        canonical = tokens[0]

        # look up the word in the index; returns None if it was never indexed
        inner = self._index.get(canonical)
        if not inner:
            return {}

        # return copies of the postings so callers cannot accidentally change the index
        # list() copies the positions list; PagePosting() creates a new object
        return {u: PagePosting(p.frequency, list(p.positions)) for u, p in inner.items()}

    def has_term(self, term: str) -> bool:
        # tokenize the input to get its canonical form; reject multi-word inputs
        tokens = tokenize(normalize_term(term))
        if len(tokens) != 1:
            return False
        # check whether the word is in the index
        return tokens[0] in self._index

    def terms(self) -> Iterator[str]:
        # return the indexed words in alphabetical order as a lazy iterator
        # Docs: https://docs.python.org/3/library/functions.html#sorted
        return iter(sorted(self._index.keys()))

    def __len__(self) -> int:
        # returns how many unique words are in the index
        # Docs: https://docs.python.org/3/reference/datamodel.html#object.__len__
        return len(self._index)

    def corpus_document_count(self) -> int:
        """
        Number of indexed page URLs (including pages with no tokens), at least ``1``.

        Used for IDF denominators so counts stay correct if documents are added
        after a :class:`~search.SearchService` is constructed.
        """
        # count all URLs we have ever indexed, including ones with no words
        # max(..., 1) makes sure we never return 0, which would cause a division error
        # Docs: https://docs.python.org/3/library/functions.html#max
        return max(len(self._url_terms), 1)

    def internal_map(self) -> Mapping[str, Mapping[str, PagePosting]]:
        """Read-only view of the underlying index (for persistence layers)."""
        # Mapping is a read-only version of dict so callers cannot change the index directly
        # Docs: https://docs.python.org/3/library/typing.html#typing.Mapping
        return self._index

    @staticmethod
    def posting_to_dict(posting: PagePosting) -> Dict[str, object]:
        # convert a PagePosting to a plain dict that json.dump() can save to a file
        # Docs: https://docs.python.org/3/library/json.html
        return {"frequency": posting.frequency, "positions": posting.positions}

    @staticmethod
    def posting_from_dict(data: Mapping[str, object]) -> PagePosting:
        # int() converts the value in case it was stored as a string instead of a number
        freq = int(data.get("frequency", 0))

        # get the list of positions, defaulting to empty if the key is missing
        pos = data.get("positions", [])

        # if positions is not a list (e.g. corrupted data), treat it as empty
        if not isinstance(pos, list):
            pos = []

        # make sure every position is an integer
        positions = [int(p) for p in pos]
        return PagePosting(frequency=freq, positions=positions)

    def to_serializable(self) -> Dict[str, Dict[str, Dict[str, object]]]:
        """Nested dicts suitable for JSON/msgpack/etc."""
        out: Dict[str, Dict[str, Dict[str, object]]] = {}
        for term, by_url in self._index.items():
            # convert each PagePosting to a plain dict so json.dump() can write it to a file
            out[term] = {
                url: Indexer.posting_to_dict(p) for url, p in by_url.items()
            }
        return out

    def load_serializable(self, data: Mapping[str, Mapping[str, Mapping[str, object]]]) -> None:
        """Replace this index from :meth:`to_serializable` output."""
        # clear any existing data before loading so we start fresh
        self.clear()
        for term, by_url in data.items():
            inner: Dict[str, PagePosting] = {}
            for url, payload in by_url.items():
                # rebuild each PagePosting from the dict we saved earlier
                inner[url] = Indexer.posting_from_dict(payload)
            self._index[term] = inner

            # rebuild the reverse map so _purge_url and corpus_document_count work correctly
            # setdefault() gets or creates the set for this URL
            for url in inner:
                self._url_terms.setdefault(url, set()).add(term)