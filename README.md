# COMP3011 Coursework 2 — Search Engine Tool

## Project overview

**Python command-line search tool** for [quotes.toscrape.com](https://quotes.toscrape.com/). It crawls the site with a **6-second politeness delay**, builds and saves an **inverted index** with per-page term statistics, and supports **`build`**, **`load`**, **`print`**, and **TF-IDF-ranked `find`** queries. Module: **COMP3011** (Web Services and Web Data).

## Features

- **Polite crawling:** at least **6 seconds** between successive HTTP GET attempts (none before the first).
- **Inverted index:** case-insensitive tokenisation (`[a-z0-9]+`); per-page **frequency** and **positions**; serialised to **`data/index.json`**.
- **Search:** **`print`** for one term; **`find`** for multi-term **Boolean AND**, then **TF-IDF** ranking, printed as `score url`.
- **Tests:** mocked HTTP for the crawler; CLI coverage for `main`.

## How it works

1. **`build`** crawls the site with politeness; the **crawler** returns each page as `(url, plain text)`.
2. The **indexer** tokenises text and builds the inverted index; results are written to **`data/index.json`**.
3. **`load`** reads the JSON into memory (or **`print`** / **`find`** **auto-load** it when you start fresh).
4. **`print <word>`** shows postings; **`find <terms...>`** keeps pages that match **all** terms (AND), then ranks them by **TF-IDF**.

## Architecture

- **`crawler.py`** — fetches pages, extracts quote-focused text (with fallback), follows same-host links.
- **`indexer.py`** — builds the inverted index (term → URL → frequency and positions).
- **`search.py`** — `print` lookups and TF-IDF-ranked `find`.
- **`main.py`** — CLI (`build`, `load`, `print`, `find`) and JSON persistence under `data/index.json`.

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
| `python src/main.py find <terms...>` | List pages containing **all** given terms (space-separated), ranked by TF-IDF and shown as `score url`. |

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

**`find`** (multi-term AND, then TF-IDF). Representative ranked lines from a real full **`build`**—scores are four decimal places; exact URLs depend on your query and index:

```text
13.9710 https://quotes.toscrape.com/author/Albert-Einstein
6.6379 https://quotes.toscrape.com/page/2/
```

## Testing

Run the full suite:

```bash
pytest
```

`tests/conftest.py` adds `src/` to `sys.path` by walking upward from the test directory until it finds `src/indexer.py`, so imports work whether you run `pytest` from the repository root or from `tests/`.

Optional coverage (shows lines not exercised by tests):

```bash
pytest --cov=src --cov-report=term-missing
```

On some **macOS** setups, `pytest` may still print one harmless **urllib3 / LibreSSL** notice in the warnings summary; it does not fail tests. Running `python src/main.py --help` stays quiet because `main.py` filters that warning before importing the crawler.

## Design decisions (short)

- **Inverted index:** maps each canonical term to URLs with `PagePosting` (frequency + positions in the page token stream).
- **Tokenisation:** lowercased alphanumeric tokens; punctuation removed; anything outside ``[a-z0-9]`` splits tokens (hyphens, apostrophes—so ``don't`` → ``don``, ``t``; same rules for indexing and queries).
- **`find`:** intersection of URL sets per term (AND), not phrase proximity.
- **Ranking:** after AND filtering, each remaining page is scored with TF-IDF (`sum(tf * idf)` over query terms) and sorted by descending score; URL is used as deterministic tie-break.
- **Crawler:** breadth-first traversal of same-host links; text from each ``div.quote span.text`` when present (quotes.toscrape.com layout), else whole-page visible text (scripts/styles stripped).
- **Politeness:** delay before every request after the first, including after failures—keeps spacing between outbound calls predictable.

## Benchmarking

I compared the old baseline (Boolean AND + alphabetical URL sort) against the current TF-IDF ranked search on the same built corpus (`data/index.json`), using `time.perf_counter()` over 2,000 repeated runs per query in a local environment.

| Query | Baseline AND + alpha sort (ms/query) | AND + TF-IDF rank (ms/query) | Overhead |
|---|---:|---:|---:|
| `love` | 0.0102 | 0.0277 | +170.9% |
| `truth` | 0.0053 | 0.0135 | +155.4% |
| `change world` | 0.0129 | 0.0260 | +101.5% |
| `good friends` | 0.0148 | 0.0334 | +125.3% |
| `life` | 0.0172 | 0.0477 | +178.1% |
| **Average** | **0.0121** | **0.0297** | **+145.6%** |

TF-IDF ranking adds a small absolute query-time cost (about `+0.018 ms/query` on this corpus) while improving result ordering for demos and relevance. Because tag pages also contain quote cards, they remain valid indexed documents and may rank highly for some queries—this follows from full-site crawling and TF-IDF scoring, not from a broken ranker.

## Error handling / edge cases

- **Empty `find`:** `python src/main.py find` with no terms (allowed by argparse) prints **No query terms.** and exits cleanly.
- **Missing index file:** `load` / `print` / `find` report an error when no `data/index.json` exists yet.
- **Unknown word (`print`):** message that there are no postings.
- **No matching pages (`find`):** message when the AND query matches nothing.
- **Crawler:** failed requests and non-200 responses are recorded and skipped without stopping the crawl.
- **Case:** indexing and search are case-insensitive.