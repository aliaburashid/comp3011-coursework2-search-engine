## TF-IDF Result Interpretation (Tag Pages Ranking High)

When `find` shows many tag pages near the top (for example `tag/love/`, `tag/love/page/1/`, `tag/friendship/`), this is expected behavior, not a bug.

- The crawler indexes the whole `quotes.toscrape.com` site (same-host scope), not only author pages.
- Tag pages are valid crawled/indexed documents in that scope.
- Those pages contain many quote cards and repeated thematic terms.
- TF-IDF therefore can score them highly for related queries.

Suggested explanation:

> High-ranking tag pages reflect the chosen crawl scope and document definition, rather than a ranking failure. A stricter corpus policy could exclude or down-weight hub/list pages, but this project keeps them for full-site coverage and reproducibility.

## IDF corpus size (design)

TF-IDF uses `Indexer.corpus_document_count()` on **each** `find` query (number of indexed URLs, minimum 1 for an empty index). That keeps IDF denominators correct if documents are added after constructing `SearchService`—unlike caching the count once.

## Tokenisation and contractions

The tokenizer only keeps `[a-z0-9]+`, so apostrophes split words: `don't` → `don`, `t`; `it's` → `it`, `s`. That is intentional and documented—fine for this coursework; mention it if asked about matching contractions literally.
