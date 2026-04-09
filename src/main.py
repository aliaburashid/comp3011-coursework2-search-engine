"""
CLI entrypoint: ``build``, ``load``, ``print <word>``, ``find <terms>``.

The compiled index defaults to ``data/index.json`` under the project root
(parent of ``src/``). Within one process, ``load`` or ``build`` fills an
in-memory index; ``print`` / ``find`` also auto-load from that file when the
process starts fresh so separate terminal invocations still work after
``build``.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import List, Optional

# macOS / LibreSSL: suppress urllib3's one-time OpenSSL notice (before requests imports urllib3).
warnings.filterwarnings(
    "ignore",
    message=r".*urllib3 v2 only supports OpenSSL.*",
)

from crawler import crawl_to_indexer_payload
from indexer import Indexer
from search import SearchService

# Resolved against this file: repo_root/data/index.json
INDEX_FILE = Path(__file__).resolve().parent.parent / "data" / "index.json"

# In-memory index for the current process (survives multiple commands only in a REPL).
_loaded_index: Optional[Indexer] = None


def _load_json_index(path: Path) -> Indexer:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    with path.open(encoding="utf-8") as handle:
        blob = json.load(handle)
    idx = Indexer()
    idx.load_serializable(blob)
    return idx


def _save_json_index(path: Path, idx: Indexer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(idx.to_serializable(), handle, ensure_ascii=False, indent=2)


def _ensure_index_ready() -> Optional[Indexer]:
    """Return a ready :class:`~indexer.Indexer` or ``None`` if no data on disk."""
    global _loaded_index
    if _loaded_index is not None:
        return _loaded_index
    if INDEX_FILE.is_file():
        _loaded_index = _load_json_index(INDEX_FILE)
        return _loaded_index
    return None


def _cmd_build() -> int:
    global _loaded_index
    rows = crawl_to_indexer_payload()
    idx = Indexer()
    for page_url, plain in rows:
        idx.add_document(page_url, plain)
    _save_json_index(INDEX_FILE, idx)
    _loaded_index = idx
    term_count = len(idx)
    print(f"Indexed {len(rows)} pages, {term_count} unique terms; wrote {INDEX_FILE}")
    return 0


def _cmd_load() -> int:
    global _loaded_index
    try:
        _loaded_index = _load_json_index(INDEX_FILE)
    except FileNotFoundError:
        print(f"Error: no index file at {INDEX_FILE}. Run build first.", file=sys.stderr)
        return 1
    print(f"Loaded index ({len(_loaded_index)} terms) from {INDEX_FILE}")
    return 0


def _cmd_print(word: str) -> int:
    idx = _ensure_index_ready()
    if idx is None:
        print("Error: no index on disk. Run build first, then load or use print/find.", file=sys.stderr)
        return 1
    lookup = SearchService(idx)
    postings = lookup.postings_for_print(word)
    if not postings:
        print(f"No postings for {word!r}.")
        return 0
    print(f"Postings for {word!r}:")
    for url in sorted(postings.keys()):
        stats = postings[url]
        print(f"  {url}")
        print(f"    frequency: {stats.frequency}")
        print(f"    positions: {stats.positions}")
    return 0


def _cmd_find(term_tokens: List[str]) -> int:
    idx = _ensure_index_ready()
    if idx is None:
        print("Error: no index on disk. Run build first.", file=sys.stderr)
        return 1
    query = " ".join(term_tokens)
    # Empty find (no tokens after join) is valid user input; handle without error.
    if not query.strip():
        print("No query terms.")
        return 0
    lookup = SearchService(idx)
    hits = lookup.scored_urls_for_find(query)
    if not hits:
        print("No matching pages.")
        return 0
    for url, score in hits:
        print(f"{score:.4f} {url}")
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="COMP3011 search tool: crawl quotes.toscrape.com, build index, query.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("build", help="Crawl the site, build index, save to data/index.json")
    sub.add_parser("load", help="Load index from data/index.json into memory")

    p_print = sub.add_parser("print", help="Show inverted-index postings for one word")
    p_print.add_argument("word", help="Single token (same token rules as the indexer)")

    p_find = sub.add_parser("find", help="List pages containing all query terms (AND), ranked")
    p_find.add_argument(
        "terms",
        nargs="*",
        help="One or more words; multi-word queries use Boolean AND",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    if args.command == "build":
        return _cmd_build()
    if args.command == "load":
        return _cmd_load()
    if args.command == "print":
        return _cmd_print(args.word)
    if args.command == "find":
        return _cmd_find(list(args.terms))
    return 1  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())  # pragma: no cover
