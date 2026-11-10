# Local validation — 2026-11-10

Historical record for the ingestion milestone. For the current implemented
database/index/search checks, see [retrieval validation](../reports/retrieval-validation-2026-11-10.md).

This records checks actually run for the first ingestion milestone. It does not
claim that the planned chatbot or hybrid retrieval is implemented.

## Python

- Windows, Python 3.12.10, uv 0.12.23.
- Dependencies resolved and installed locally; exact versions recorded in `uv.lock`.
- `python -m pytest -q`: **25 passed**. Mock HTTP only; no website or paid API calls.
- `ruff check .`: passed.
- `ruff format --check .`: passed.
- `python -m compileall -q src`: passed.

Tests exercise same-origin restrictions, robots wildcards and redirect checks,
fail-closed robots loading, XML entity rejection, metadata extraction and source
warnings, section boundaries, stable IDs, offline reprocessing, navigation-page
exclusion, animated counters, retry bounds and response-size limits.

## PostgreSQL

Docker Desktop was started locally. `docker compose up -d` created the project
database and its persistent volume. The container became healthy with pgvector
**0.8.7** installed.

`db/smoke.sql` passed against the real container: it inserted linked test documents,
chunks, vectors and a snapshot, checked cosine distance, rejected inconsistent
vector dimensions and a second active snapshot, then rolled back every test row.

The database is initialized but the scraped corpus has not been loaded. The local
`.env` has a generated password and is ignored by Git.

## Website evidence

The initial live sample covered 15 URLs, including a job, course and training.
No page-fetch failures were recorded for that sample. Original source HTML and
versioned extraction artifacts are retained locally, not committed.

See `reports/` for generated inventory and crawl counts. Those are observations
from specific runs: the live site's sitemaps changed between the first two audits.

The subsequent full crawl attempted **546 URLs** and accepted **542 canonical
documents**, with four canonical duplicates and no fetch failures. Offline
reprocessing produced **2,356 chunks** from **167 eligible documents**. Artifact
integrity checks verified unique chunk IDs, raw HTML for every document, no
accepted noindex documents, the configured word-count ceiling and no leaked
Bricks loop comments in chunk text. The final extraction had no unstructured
fallbacks; 60 documents carried source metadata warnings for review.

## Limits

JavaScript is not executed, PDFs and external domains are not crawled, and the
current schema has no corpus importer. No embeddings, BM25 index, RRF, reranker,
LLM answers or chat interface have been evaluated yet. GitHub Actions are configured;
their hosted results must be checked separately from these local checks.
