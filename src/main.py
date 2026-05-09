"""
CLI entrypoint: ``build``, ``load``, ``print <word>``, ``find <terms>``.

The compiled index defaults to ``data/index.json`` under the project root
(parent of ``src/``). Within one process, ``load`` or ``build`` fills an
in-memory index; ``print`` / ``find`` also auto-load from that file when the
process starts fresh so separate terminal invocations still work after
``build``.
"""

# allows newer type hint styles to work on older Python versions
# Docs: https://peps.python.org/pep-0563/
from __future__ import annotations

# argparse is the standard library module for building command-line tools
# Docs: https://docs.python.org/3/library/argparse.html
import argparse

# json is used to save and load the index as a JSON file
# Docs: https://docs.python.org/3/library/json.html
import json

# sys.stderr lets us print error messages separately from normal output
# Docs: https://docs.python.org/3/library/sys.html#sys.stderr
import sys

# warnings lets us silence an annoying urllib3 message that appears on macOS
# Docs: https://docs.python.org/3/library/warnings.html#warnings.filterwarnings
import warnings

# Path gives us a convenient way to work with file paths
# Docs: https://docs.python.org/3/library/pathlib.html
from pathlib import Path

# used for type hints in function signatures
# Docs: https://docs.python.org/3/library/typing.html
from typing import List, Optional

# silence a urllib3/LibreSSL warning that shows up on macOS before requests is imported
# this must run before we import requests
# Docs: https://docs.python.org/3/library/warnings.html
warnings.filterwarnings(
    "ignore",
    message=r".*urllib3 v2 only supports OpenSSL.*",
)

# our crawler module that downloads pages from the website
from crawler import crawl_to_indexer_payload

# our indexer module that builds and stores the inverted index
from indexer import Indexer

# our search module that handles print and find queries
from search import SearchService

# work out the path to data/index.json relative to this file
# __file__ is the path of main.py; .parent.parent goes up to the repo root
# Docs: https://docs.python.org/3/library/pathlib.html#pathlib.Path.resolve
INDEX_FILE = Path(__file__).resolve().parent.parent / "data" / "index.json"

# holds the index in memory for the current process
# None means we have not loaded or built an index yet
_loaded_index: Optional[Indexer] = None


def _load_json_index(path: Path) -> Indexer:
    # raise an error straight away if the file does not exist
    # Docs: https://docs.python.org/3/library/pathlib.html#pathlib.Path.is_file
    if not path.is_file():
        raise FileNotFoundError(str(path))

    # open and read the JSON file
    # Docs: https://docs.python.org/3/library/pathlib.html#pathlib.Path.open
    with path.open(encoding="utf-8") as handle:
        # json.load() reads the file and converts it to Python dicts and lists
        # Docs: https://docs.python.org/3/library/json.html#json.load
        blob = json.load(handle)

    # create a new Indexer and fill it from the data we just read
    idx = Indexer()
    idx.load_serializable(blob)
    return idx


def _save_json_index(path: Path, idx: Indexer) -> None:
    # create the data/ folder if it does not already exist
    # Docs: https://docs.python.org/3/library/pathlib.html#pathlib.Path.mkdir
    path.parent.mkdir(parents=True, exist_ok=True)

    # open the file for writing (creates it if it does not exist, overwrites if it does)
    with path.open("w", encoding="utf-8") as handle:
        # json.dump() converts the index to JSON and writes it to the file
        # ensure_ascii=False keeps unicode characters (e.g. curly quotes) as-is
        # indent=2 makes the file easier to read
        # Docs: https://docs.python.org/3/library/json.html#json.dump
        json.dump(idx.to_serializable(), handle, ensure_ascii=False, indent=2)


def _ensure_index_ready() -> Optional[Indexer]:
    """Return a ready :class:`~indexer.Indexer` or ``None`` if no data on disk."""
    # global lets us update the module-level variable from inside this function
    # Docs: https://docs.python.org/3/reference/simple_stmts.html#the-global-statement
    global _loaded_index

    # if an index is already in memory, use it without touching the file
    if _loaded_index is not None:
        return _loaded_index

    # if the index file exists on disk, load it automatically
    if INDEX_FILE.is_file():
        _loaded_index = _load_json_index(INDEX_FILE)
        return _loaded_index

    # no index in memory and no file on disk — the user needs to run build first
    return None


def _cmd_build() -> int:
    global _loaded_index

    # run the crawler to download all pages and get back a list of (url, text) pairs
    rows = crawl_to_indexer_payload()

    # create a fresh index and add every crawled page to it
    idx = Indexer()
    for page_url, plain in rows:
        # add_document tokenises the text and updates the index for this URL
        idx.add_document(page_url, plain)

    # save the finished index to data/index.json
    _save_json_index(INDEX_FILE, idx)

    # keep the index in memory so print/find in the same session do not need to reload it
    _loaded_index = idx

    term_count = len(idx)
    # tell the user how many pages were indexed and how many unique words were found
    print(f"Indexed {len(rows)} pages, {term_count} unique terms; wrote {INDEX_FILE}")
    return 0


def _cmd_load() -> int:
    global _loaded_index
    try:
        # try to read the index from disk
        _loaded_index = _load_json_index(INDEX_FILE)
    except FileNotFoundError:
        # the file does not exist yet — tell the user to run build first
        # sys.stderr — Docs: https://docs.python.org/3/library/sys.html#sys.stderr
        print(f"Error: no index file at {INDEX_FILE}. Run build first.", file=sys.stderr)
        return 1

    # tell the user how many words were loaded
    print(f"Loaded index ({len(_loaded_index)} terms) from {INDEX_FILE}")
    return 0


def _cmd_print(word: str) -> int:
    # make sure we have an index available before trying to search it
    idx = _ensure_index_ready()
    if idx is None:
        print("Error: no index on disk. Run build first, then load or use print/find.", file=sys.stderr)
        return 1

    # wrap the index in SearchService to run the lookup
    lookup = SearchService(idx)
    postings = lookup.postings_for_print(word)

    # if the word was not found in the index, say so clearly
    if not postings:
        print(f"No postings for {word!r}.")
        return 0

    print(f"Postings for {word!r}:")
    # sorted() puts the URLs in alphabetical order for consistent output
    # Docs: https://docs.python.org/3/library/functions.html#sorted
    for url in sorted(postings.keys()):
        stats = postings[url]
        print(f"  {url}")
        # show how many times the word appears and at which positions
        print(f"    frequency: {stats.frequency}")
        print(f"    positions: {stats.positions}")
    return 0


def _cmd_find(term_tokens: List[str]) -> int:
    # make sure we have an index available
    idx = _ensure_index_ready()
    if idx is None:
        print("Error: no index on disk. Run build first.", file=sys.stderr)
        return 1

    # rejoin the words into a single string so SearchService can tokenise them
    query = " ".join(term_tokens)

    # Empty find (no tokens after join) is valid user input; handle without error.
    if not query.strip():
        print("No query terms.")
        return 0

    lookup = SearchService(idx)

    # scored_urls_for_find returns (url, score) pairs sorted by relevance
    hits = lookup.scored_urls_for_find(query)

    if not hits:
        print("No matching pages.")
        return 0

    for url, score in hits:
        # show the score to 4 decimal places followed by the URL
        # :.4f format — Docs: https://docs.python.org/3/library/string.html#format-specification-mini-language
        print(f"{score:.4f} {url}")
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    # create the top-level parser with a description that shows in --help
    # Docs: https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser
    parser = argparse.ArgumentParser(
        description="COMP3011 search tool: crawl quotes.toscrape.com, build index, query.",
    )

    # add_subparsers() lets us define separate sub-commands (build, load, print, find)
    # required=True means the user must type one of them
    # Docs: https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser.add_subparsers
    sub = parser.add_subparsers(dest="command", required=True)

    # register each sub-command
    sub.add_parser("build", help="Crawl the site, build index, save to data/index.json")
    sub.add_parser("load", help="Load index from data/index.json into memory")

    # print needs exactly one argument: the word to look up
    p_print = sub.add_parser("print", help="Show inverted-index postings for one word")
    p_print.add_argument("word", help="Single token (same token rules as the indexer)")

    # find accepts zero or more words; nargs='*' allows an empty list
    # Docs: https://docs.python.org/3/library/argparse.html#nargs
    p_find = sub.add_parser("find", help="List pages containing all query terms (AND), ranked")
    p_find.add_argument(
        "terms",
        nargs="*",
        help="One or more words; multi-word queries use Boolean AND",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    # parse the command-line arguments into a Namespace object
    # Docs: https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser.parse_args
    args = _build_arg_parser().parse_args(argv)

    # call the right function depending on which sub-command the user typed
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
    # SystemExit passes the return value of main() as the process exit code
    # Docs: https://docs.python.org/3/library/exceptions.html#SystemExit
    raise SystemExit(main())  # pragma: no cover