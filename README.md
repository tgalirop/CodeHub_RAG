# CodeHub RAG

Hybrid RAG assistant for the public content of [Code.Hub](https://codehub.gr/).
Independent portfolio project by [tgalirop](https://github.com/tgalirop).

## Open the chatbot

```powershell
uv sync --locked
docker compose up -d postgres
uv run codehub-rag serve
```

Open **http://127.0.0.1:8000**. The local development instance is already running.
The branded UI uses real hybrid retrieval and streams OpenAI answers with source
citations. Configure `OPENAI_API_KEY` only in the root `.env`; without it the UI
clearly shows source-only preview results. Conversation history stays in the browser.

For personal demo hosting, use **Vercel + Neon Free**, with **Root Directory `web`**.
The Node.js API performs hybrid retrieval directly against hosted PostgreSQL;
BM25 weights/statistics are persisted in the database and no local model is bundled.
OpenAI embeddings and answers are charged separately from hosting.
See [complete deployment instructions](docs/deployment.md) for export, resumable
API embeddings, atomic database publication and Vercel environment variables.
The original Python-container relay remains available as an alternative.

See [chatbot validation](reports/chat-validation-2026-11-10.md) for live API checks,
automated tests, Linux container validation and the browser-verification limit.

## Current milestone: local hybrid retrieval

Latest full crawl (2026-11-10): **546 URLs attempted, 542 canonical documents,
167 documents eligible for retrieval and zero fetch errors**.
Four duplicate canonical responses were excluded. See the
[full audit report](reports/site-audit-2026-11-10.md).

The active retrieval snapshot contains **2,481 token-budgeted chunks and 384-dimensional
multilingual embeddings**. PostgreSQL, persisted BM25 and hybrid search are implemented.
See [retrieval validation](reports/retrieval-validation-2026-11-10.md).

Implemented and runnable:

- Discover the site's declared sitemaps, including nested sitemap indexes.
- Produce a deduplicated URL inventory grouped by sitemap category.
- Respect robots rules, including wildcard filters and rules on redirect targets.
- Fetch sequentially with rate limiting, retries, timeouts and response-size limits.
- Extract main content, headings, tables, canonical URLs, language and JSON-LD metadata.
- Preserve original HTML locally and produce versioned documents and section-aware chunks.
- Report failures, thin content, fallback extraction and links missing from sitemaps.
- Flag malformed/conflicting JSON-LD dates, event status and salary units for review.
- Resolve Bricks animated counters from explicit source targets instead of indexing placeholder zeros.
- Keep taxonomy pages in the audit while excluding them from retrieval chunks.
- Import document versions and chunks transactionally into PostgreSQL + pgvector.
- Cache pinned local E5-small embeddings by model and exact input hash.
- Save BM25S weights, vocabulary, document frequencies, IDF, lengths and average length.
- Search with dense cosine similarity, BM25 or canonical-page RRF hybrid ranking.
- Filter both retrievers by page/course/job/training/post category.
- Activate validated, immutable snapshots atomically; verify artifact checksums on load.
- Preserve original Code.Hub logo and source color tokens under `assets/brand/`.

**Implemented chat layer:** FastAPI local preview, OpenAI Responses with source
citations, branded responsive UI and a direct Vercel Node.js/PostgreSQL hybrid API.
The cloud mode uses `text-embedding-3-small` (384 dimensions), a private `rag_cloud`
schema, persisted BM25 postings, atomic snapshots and durable demo request limits.
Cloud provisioning/data upload are separate from deploying the frontend. CLI search commands
continue returning source passages. Cross-encoder reranking and independent
answer-quality evaluation remain next milestones.

## Run hybrid search (PowerShell)

For a fresh checkout, first collect a full crawl as described below, start Docker,
and create `.env` from `.env.example` with a local database password. On the existing
development machine these steps and indexing have already been completed.

```powershell
uv sync --locked
docker compose up -d
uv run codehub-rag migrate
uv run codehub-rag model-download
uv run codehub-rag index data/runs/YOUR_FULL_RUN
uv run codehub-rag search "Θέλω εκπαίδευση της ομάδας μου" --limit 5
uv run codehub-rag search "C# ASP.NET Core" --kind course
uv run codehub-rag search "Lead ML Engineer" --kind job --mode bm25
uv run codehub-rag search --interactive
```

`model-download` fetches a pinned multilingual E5-small ONNX model (~470 MB plus
tokenizer files). Embedding inference runs locally on CPU. No paid API key is needed.
Use `--models` to choose a model-cache root, and `--threads` to control inference threads.

`index` prepares passages within the model's 512-token budget, imports the corpus,
reuses existing vectors, saves BM25 and activates a validated snapshot. An incomplete
crawl cannot be activated. Interrupted embedding builds can be rerun; completed
batches are cached. Repeating a successful build reuses vectors and the BM25 artifact.
`load YOUR_RUN` is also available to import source documents/chunks without indexing.

`search` supports `--mode hybrid`, `dense` or `bm25`. Hybrid search expands selected
Greek domain terms using a versioned bilingual glossary, retrieves candidates from
both indexes, merges rankings by canonical page and returns passages with URLs,
timestamps and source warnings. Scores are ranking signals, not confidence percentages.
Interactive mode loads the model and BM25 once for the whole session.

```powershell
uv run codehub-rag evaluate --output data/retrieval-evaluation.json
```

The 20 positive smoke questions are a development set used while improving retrieval,
not a held-out benchmark. The full question list, baseline and latest results are in
`evaluation/` and `reports/`. LLM answer correctness and abstention are not measured yet.

## Quick start (PowerShell)

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```powershell
uv sync --locked
uv run codehub-rag audit --sample 15
```

The audit visits all declared sitemaps and downloads a sample of 15 pages. It does
not crawl the entire website by default. Samples prioritize the homepage and rotate
through page, job, course, training, post and taxonomy categories.

For sitemap discovery only:

```powershell
uv run codehub-rag audit --sample 0
```

Each audit creates a new timestamped directory under `data/runs/`. Use its actual
path in the following command to fetch all inventory pages and follow additional
in-scope HTML links:

```powershell
uv run codehub-rag crawl data/runs/YOUR_RUN --all --discover
```

If that run already contains extracted documents, add `--overwrite` to replace its
extraction outputs. This re-fetches pages; it is not a resume or incremental crawl.
The CLI returns exit code 2 for partial sitemap/page failures, 1 for fatal failures.
Check `audit.json` and `crawl.json`, rather than treating process completion as proof
of full coverage. The default minimum request interval is 0.8 seconds; `--delay`
can increase it and a declared robots crawl delay takes precedence.

## Local output

| Artifact | Purpose |
| --- | --- |
| `audit.json` | Counts by sitemap category, sitemap failures and inventory completeness |
| `inventory.jsonl` | Deduplicated page URLs, source sitemaps and source lastmod values |
| `exclusions.jsonl` | URLs excluded by robots rules or crawl scope |
| `raw/` | Original robots.txt, sitemap XML and fetched page HTML |
| `documents.jsonl` | Extracted content, metadata, provenance and content hashes |
| `chunks.jsonl` | Stable chunk IDs, heading context and source URLs |
| `discovered_links.jsonl` | Internal links and whether they appeared in the sitemap |
| `crawl.json` | Extraction counts, errors, exclusions and quality flags |
| `summary.json` | Latest ingestion command's combined report |

Raw website content and generated data are ignored by Git. A reviewed audit summary
can be committed under `reports/` without committing the scraped corpus.

```powershell
uv run codehub-rag report data/runs/YOUR_RUN --output reports/site-audit.md
```

To iterate on extraction using saved HTML, without downloading those pages again:

```powershell
uv run codehub-rag reprocess data/runs/YOUR_RUN
```

This replaces the accepted documents, chunks and quality report in that run; it
preserves the original HTML and fetch timestamps. It reprocesses previously accepted
documents only. It does not retry failed, skipped or noindex pages. Source metadata
conflicts are flagged and retained, not silently corrected.

## PostgreSQL and stored indexes

Requires a running Docker engine. Create `.env` and set a local password:

```powershell
Copy-Item .env.example .env
# Edit .env and set POSTGRES_PASSWORD, then:
docker compose up -d
docker compose ps
```

PostgreSQL listens on localhost only and uses a persistent Docker volume. The
initial schema is applied **only when that database volume is first initialized**;
later schema changes use `uv run codehub-rag migrate`. Do not remove the volume to apply changes
to a database containing valuable data.

Migrations are tracked with checksums and applied transactionally. The original
milestone-one schema is adopted without deleting data. Historical document versions
and retrieval snapshots are retained. New imports do not change a loaded search
session's pinned snapshot.

Vectors use pgvector exact cosine search over the snapshot's members. With this
corpus size an approximate index is unnecessary; HNSW remains an option if the
corpus grows. All corpus-wide BM25 work happens during indexing, never per question.

Artifacts under `data/indexes/SNAPSHOT_ID/` contain the saved BM25 arrays,
`statistics.json` and a checksummed `manifest.json`. PostgreSQL records the artifact
path, model configuration and exact chunk-position mapping. The indexer and search
worker currently need access to the same artifact path; artifacts are not stored
inside the PostgreSQL Docker volume. Back up both `data/` and the database volume.

After migrations, validate vector operations and snapshot
constraints with a transaction that rolls back its test rows:

```powershell
Get-Content db/smoke.sql -Raw | docker compose exec -T postgres psql -U codehub -d codehub_rag -v ON_ERROR_STOP=1
```

The same Python checks and fresh-database smoke test are configured in GitHub Actions.

## Retrieval pipeline

```text
Website → inventory → extraction → versioned chunks
                                    ├─ PostgreSQL / pgvector
                                    └─ persisted BM25S artifact

Question → bilingual glossary + multilingual embedding + lexical tokenization
         → dense retrieval + BM25 → canonical-page RRF → source passages

Current web: source passages → grounded LLM answer → branded chat interface
Planned: cross-encoder reranking before answer generation
```

BM25 corpus statistics and weights are persisted during indexing. SearchEngine
loads that artifact once per session/worker. A retrieval snapshot ties its chunk
ordering and checksum to the same chunk set used for vectors. A failed build leaves
the previous active snapshot available.

See [architecture decisions](docs/architecture.md) for scope and remaining work.

## Checks

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Default tests use mock HTTP and no model downloads or paid APIs. Six database
integration tests are opt-in and require a dedicated database whose name ends in `_test`:

```powershell
docker compose exec -T postgres createdb -U codehub codehub_rag_test
$env:POSTGRES_DB = "codehub_rag_test"
$env:CODEHUB_TEST_DB = "1"
uv run pytest tests/test_database.py -q
Remove-Item Env:POSTGRES_DB
Remove-Item Env:CODEHUB_TEST_DB
```

GitHub Actions run both the default checks and the real-database integration tests.
