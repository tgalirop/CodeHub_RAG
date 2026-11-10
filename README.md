# CodeHub RAG

Hybrid RAG assistant for the public content of [Code.Hub](https://codehub.gr/).
Independent portfolio project by [tgalirop](https://github.com/tgalirop).

## Current milestone: site audit and ingestion

Latest full crawl (2026-11-10): **546 URLs attempted, 542 canonical documents,
167 documents eligible for retrieval, 2,356 chunks and zero fetch errors**.
Four duplicate canonical responses were excluded. See the
[full audit report](reports/site-audit-2026-11-10.md).

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
- Provide a PostgreSQL + pgvector schema for the next ingestion milestone.
- Preserve original Code.Hub logo and source color tokens under `assets/brand/`.

**Not implemented yet:** database loading, embeddings, persisted BM25 indexing, hybrid
retrieval, reranking, answer generation and the branded chat interface. The SQL is a
foundation, not evidence that PostgreSQL has been started or populated.

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

## PostgreSQL foundation

Requires a running Docker engine. Create `.env` and set a local password:

```powershell
Copy-Item .env.example .env
# Edit .env and set POSTGRES_PASSWORD, then:
docker compose up -d
docker compose ps
```

PostgreSQL listens on localhost only and uses a persistent Docker volume. The
initial schema is applied **only when that database volume is first initialized**;
later schema changes require migrations. Do not remove the volume to apply changes
to a database containing valuable data.

`db/001_initial.sql` includes pages, immutable document versions, chunks, vectors
and retrieval snapshots. Vector dimensions and ANN indexes will be selected after
the embedding-model evaluation. No embedding or LLM credentials are needed for the
current audit and extraction commands.

On a freshly initialized database, validate vector operations and snapshot
constraints with a transaction that rolls back its test rows:

```powershell
Get-Content db/smoke.sql -Raw | docker compose exec -T postgres psql -U codehub -d codehub_rag -v ON_ERROR_STOP=1
```

The same Python checks and fresh-database smoke test are configured in GitHub Actions.

## Planned retrieval

```text
Website → inventory → extraction → versioned chunks
                                    ├─ PostgreSQL / pgvector
                                    └─ persisted BM25S artifact

Question → multilingual embedding + lexical tokenization
         → dense retrieval + BM25 → RRF → reranker
         → grounded answer with links to Code.Hub sources
```

BM25 corpus statistics and weights will be built during indexing and persisted.
The API will load that artifact at startup instead of rebuilding it per question.
A retrieval snapshot will tie its chunk ordering and checksum to the same chunk
set used for vectors. New snapshots must be validated before becoming active.

See [architecture decisions](docs/architecture.md) for scope and remaining work.

## Checks

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Tests use a mock HTTP transport: they do not access the website or paid APIs.
