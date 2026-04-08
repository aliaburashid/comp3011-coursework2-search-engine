# COMP3011 Coursework 2 — Search Engine Tool

## Project overview

Individual **Python command-line** tool for [quotes.toscrape.com](https://quotes.toscrape.com/): it **crawls** the site (polite delay between requests), **builds an inverted index** with per-page word statistics, **saves** the index to disk, and **searches** with `print` (single word) and `find` (multi-word **AND**). Target module: **COMP3011** (Web Services and Web Data).

## Features

- **Polite crawling:** at least **6 seconds** between successive HTTP GET attempts (none before the first).
- **Indexing:** case-insensitive tokenisation (`[a-z0-9]+`); inverted index stores **frequency** and **token positions** per page.
- **Persistence:** index serialised as **JSON** at `data/index.json`.
- **Search:** `find` uses **Boolean AND** over query terms; results are sorted URLs (unranked; TF-IDF noted as a possible extension).
- **Tests:** automated suite with **mocked HTTP** for the crawler and CLI tests for `main`.

## How it works

1. **`build`** crawls [quotes.toscrape.com](https://quotes.toscrape.com/) page by page (polite gaps between requests).
2. The **crawler** returns each page as `(url, plain text)`.
3. The **indexer** tokenises the text and updates the **inverted index** (word → URLs → frequency and positions).
4. The index is **saved** to `data/index.json`.
5. **`print <word>`** looks up **one** term and shows where it appears.
6. **`find <terms...>`** lists URLs whose text contains **all** of those terms (AND).

## Repository layout

```text
comp3011-coursework2-search-engine/
  src/
    crawler.py          # downloads pages, follows links, waits 6s between requests, gets text
    indexer.py          # builds the word index (counts + positions), can save/load as JSON
    search.py           # looks up one word (print) or all words at once (find)
    main.py             # the commands you type: build, load, print, find
  tests/
    conftest.py         # helps tests find the code in src/
    test_crawler.py     # tests the crawler (no real website in tests)
    test_indexer.py     # tests the indexer
    test_search.py      # tests search
    test_main.py        # tests the CLI
  data/
    index.json          # saved index after you run build (hand this in)
  requirements.txt      # list of Python packages to install
  README.md             # how to install and run (this file)
```

## Installation / setup

```bash
git clone <your-repo-url>
cd comp3011-coursework2-search-engine
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Dependencies

| Package | Role |
|---------|------|
| **requests** | HTTP client for the crawler (as recommended by the brief) |
| **beautifulsoup4** | HTML parsing (as recommended) |
| **pytest** | Test runner |
| **pytest-cov** | Coverage reports (optional but useful) |

Install everything with `pip install -r requirements.txt`.

## Usage

Run commands from the **repository root** (the directory that contains `src/` and `data/`).

| Command | What it does |
|---------|----------------|
| `python src/main.py build` | Crawl the site, build the index, write `data/index.json`, print page count and unique term count. **Expect long runtime** (6s between requests). |
| `python src/main.py load` | Load `data/index.json` into memory. |
| `python src/main.py print <word>` | Show inverted-index postings (frequency and positions) for **one** token. |
| `python src/main.py find <terms...>` | List page URLs that contain **all** given terms (space-separated). |

Example commands:

```bash
python src/main.py build
python src/main.py load
python src/main.py print nonsense
python src/main.py find good friends
```

`print` and `find` **auto-load** `data/index.json` if the index is not already in memory (useful in a new terminal after `build`).

### Example output

Exact numbers and URLs depend on the live site and your index. After a successful **`build`**, you should see something like:

```text
$ python src/main.py build
Indexed 10 pages, 345 unique terms; wrote .../data/index.json
```

**`print`** for a word that appears on a page:

```text
$ python src/main.py print nonsense
Postings for 'nonsense':
  https://quotes.toscrape.com/page/1/
    frequency: 1
    positions: [42]
```

**`find`** with two terms (pages must contain both):

```text
$ python src/main.py find good friends
https://quotes.toscrape.com/page/1/
https://quotes.toscrape.com/page/2/
```

## Testing

Run the full suite:

```bash
pytest
```

Optional coverage (shows lines not exercised by tests):

```bash
pytest --cov=src --cov-report=term-missing
```

On some **macOS** setups, `pytest` may still print one harmless **urllib3 / LibreSSL** notice in the warnings summary; it does not fail tests. Running `python src/main.py --help` stays quiet because `main.py` filters that warning before importing the crawler.

## Design decisions (short)

- **Inverted index:** maps each canonical term to URLs with `PagePosting` (frequency + positions in the page token stream).
- **Tokenisation:** lowercased alphanumeric tokens; punctuation removed; hyphens split words (same rules for indexing and queries).
- **`find`:** intersection of URL sets per term (AND), not phrase proximity.
- **Crawler:** breadth-first traversal of same-host links; whole-page visible text (scripts/styles stripped).
- **Politeness:** delay before every request after the first, including after failures—keeps spacing between outbound calls predictable.

## Error handling / edge cases

- **Empty `find`:** prints a clear message; no crash.
- **Missing index file:** `load` / `print` / `find` report an error when no `data/index.json` exists yet.
- **Unknown word (`print`):** message that there are no postings.
- **No matching pages (`find`):** message when the AND query matches nothing.
- **Crawler:** failed requests and non-200 responses are recorded and skipped without stopping the crawl.
- **Case:** indexing and search are case-insensitive.

## GenAI declaration

Declare any generative AI tools used (and reflect critically in your video), per the module’s green-category rules and your submission checklist.
