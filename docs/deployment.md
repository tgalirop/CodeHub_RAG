# Chatbot deployment

## Recommended: Vercel + Neon Free

The frontend and the complete chat/retrieval API run on Vercel Node.js 24.
Neon stores PostgreSQL/pgvector, source passages, precomputed BM25 weights and
durable demo request counters. The computer does not need to remain online.
Existing Supabase PostgreSQL projects are also supported by the same code.

```text
Browser -> Vercel /api/chat -> OpenAI query embedding
                          -> PostgreSQL: pgvector + persisted BM25 -> page RRF
                          -> OpenAI Responses -> streamed answer + source citations
```

Hosting can stay within the providers' Free/Hobby quotas for a personal demo.
OpenAI embeddings and answers are metered separately, including the initial corpus
embedding run. Free hosting is not a guarantee of unlimited usage or availability.
Vercel Hobby is for personal, non-commercial use. Review the current
[Vercel Hobby terms](https://vercel.com/docs/plans/hobby) and
[Neon Free quotas](https://neon.com/pricing); Neon currently lists 1 GB of storage
and 100 CU-hours per month per project. Let the database scale to zero normally.

### 1. Create the separate hosted database

In [Neon Console](https://console.neon.tech/), create a Free project named
`codehub-rag`. Choose a European region near the Vercel function region if possible.
Open **Connect**, turn **Connection pooling** on, and copy the PostgreSQL URI.
Copy only the URL, not the surrounding `psql '...'` command. Keep TLS options.

In the root local `.env`, add:

```dotenv
CLOUD_DATABASE_URL="postgresql://USER:PASSWORD@YOUR-POOLER-HOST/neondb?sslmode=require"
```

Use the actual URL from Connect. Do not paste credentials into chat or Git.
Keep the existing local `POSTGRES_*` / `DATABASE_URL` settings: the export reads
the local corpus, while publication uses `CLOUD_DATABASE_URL` exclusively.
For an existing Supabase project, use its Transaction pooler URI; the alias
`SUPABASE_DATABASE_URL` is accepted when `CLOUD_DATABASE_URL` is absent.

### 2. Export, embed and publish once, from the development machine

The existing local PostgreSQL must be running and contain a ready E5 snapshot.
For a fresh checkout, run the README crawl/index steps first. Source data, local
model weights, corpus exports and embedding caches are deliberately excluded from Git.

```powershell
uv sync --locked
docker compose up -d postgres
uv run python -m codehub_rag.cloud prepare
uv run python -m codehub_rag.cloud embed
uv run python -m codehub_rag.cloud publish
uv run python -m codehub_rag.cloud status
```

`prepare` exports source passages and calculates statistics locally; it calls no
paid API. `embed` uses the local `.env` `OPENAI_API_KEY` to create **new**
`text-embedding-3-small` vectors at 384 dimensions. Old E5 vectors cannot be mixed
with this model, even though their dimensions match. Completed batches are cached
by model, dimensions and exact input hash in ignored `data/cloud/embeddings.sqlite3`.
Interrupted runs resume without re-embedding completed inputs. Keep this cache.

`publish` creates only the private `rag_cloud` schema from `cloud/schema.sql`,
copies passages, vectors, vocabulary DF/IDF and precomputed sparse BM25 postings,
checks counts and switches the active snapshot in one transaction. An upload
failure rolls back; the previous active snapshot remains available. The original
local E5 database tables are untouched. Repeating publication is idempotent.

The application reads saved BM25 weights; it does not retokenize the corpus,
rebuild BM25 statistics, download models or crawl pages per user question.
Only question tokenization, query embedding, candidate search and fusion run online.
At 2,481 chunks exact cosine search avoids an approximate-index recall tradeoff.

### 3. Configure the existing Vercel project

Keep **Root Directory `web`**, preset **Other**, build `npm run build`, output
`public`, and Node **24.x**. The committed npm lockfile installs the PostgreSQL driver.
In **Settings -> Environment Variables**, set these for **Production**:

| Variable | Value |
| --- | --- |
| `CLOUD_DATABASE_URL` | The same pooled PostgreSQL URI |
| `OPENAI_API_KEY` | A valid, rotated key, kept only server-side |
| `OPENAI_MODEL` | `gpt-6-luna`, or another Responses model your account can access |
| `RAG_DAILY_LIMIT` | `100` by default, across all visitors |
| `RAG_HOURLY_IP_LIMIT` | `20` by default, per hashed address per UTC hour |
| `RAG_RATE_LIMIT_SALT` | Optional long random secret for stable address hashing |

Do not prefix these with `VITE_` or `NEXT_PUBLIC_`. In this architecture
**`RAG_API_URL` and `RAG_API_TOKEN` are not required**. A cloud database URL takes
precedence over the legacy relay. Apply secrets to Preview only if you intend
preview deployments to share the production corpus and request budget.

After the new code reaches GitHub and the variables are saved, **Redeploy** the
latest `main` commit. Open `/api/status`: expect `ready: true`,
`backend: "vercel-postgres"`, 167 documents and 2,481 chunks for the current corpus.
Ask a contact question and check both its citation and the original source card.

### Cost and verification limits

The database atomically reserves the public demo allowance **before** a paid API
call. Invalid bodies/origins are rejected first. Defaults permit at most 100 accepted
chat requests per UTC day across deployments that share this database, and 20 per
hashed client address per UTC hour. Failed provider calls still consume a reserved
request. The counters do not store raw IP addresses or conversations. This limits
request counts, not an exact monetary budget; set OpenAI billing controls separately.
It is not a full user authentication or anti-bot system.

The Node API validates the embedding identity, dimensions and shared lexical config
against the active snapshot. Category filters apply before both candidate limits;
page RRF and distinct source selection mirror the existing local retriever.
Python tests compare persisted posting weights with BM25S. Integration tests cover
publication, actual Node/PostgreSQL search, filtering and durable counters. Mocked
provider tests cover source/delta/done ordering, incomplete streams and cancellation.
The old E5 retrieval benchmark does not establish the new API model's recall.
Real hosted end-to-end verification requires the user's database credentials and
completed corpus embeddings; do not infer success from the frontend deployment.

References: [Neon pooling](https://neon.com/docs/connect/connection-pooling),
[Neon pgvector](https://neon.com/docs/extensions/pgvector),
[OpenAI embeddings](https://developers.openai.com/api/docs/guides/embeddings),
[OpenAI streaming](https://developers.openai.com/api/docs/guides/streaming-responses).

## Run and view locally

The current development instance is available at **http://127.0.0.1:8000**.
To start it again from the repository root:

```powershell
uv sync --locked
docker compose up -d postgres
uv run codehub-rag serve
```

This serves both the UI and FastAPI on the same origin. No Node.js installation is
required for this local preview. It uses the already indexed PostgreSQL corpus,
the local embedding model and persisted BM25 artifacts. `OPENAI_API_KEY` and
`OPENAI_MODEL` are read from the root `.env` at request time. The default answer
model is `gpt-6-luna`. Missing keys enable an explicitly labeled source-only mode.
Without the existing model/index/data, complete the README indexing steps first.

The UI provides streaming replies, numeric source citations, expandable source
cards, category filters, suggested questions, stop/retry/copy, and browser-local
conversation history. Conversations are not stored in the backend. Sending a
message with an OpenAI key configured sends bounded history and retrieved website
evidence to OpenAI; Responses storage is disabled with `store=false`.

## Alternative: original Python container hosting

```text
Browser
   |
   v
Vercel: web/public + web/api/[route].js (Node.js 24)
   | HTTPS + server-side bearer token + streamed SSE
   v
FastAPI container: model + BM25 artifacts + OpenAI Responses
   |
   v
PostgreSQL with pgvector
```

Vercel hosts the complete frontend and a small server-side relay. The Python
retriever runs in a persistent container service with access to PostgreSQL and
the same model/index artifacts used during indexing. The current ONNX model is
about 470 MB before Python/runtime dependencies. It is deliberately excluded from
the Vercel deployment; this avoids oversized standard function bundles and
downloading models on serverless cold starts.

This repository is deployment-ready, but no Vercel project or remote backend has
been provisioned by the local development workflow.

### Vercel relay settings (container alternative only)

Import `tgalirop/CodeHub_RAG` and use:

| Setting | Value |
| --- | --- |
| Root Directory | `web` |
| Framework Preset | Other |
| Node.js | 24.x |
| Build Command | `npm run build` |
| Output Directory | `public` |

Set these **server-side** Vercel environment variables:

- `RAG_API_URL`: the HTTPS origin of the hosted FastAPI service.
- `RAG_API_TOKEN`: a long random shared token, identical to the backend setting.

In this container alternative no OpenAI key is needed in Vercel. Never expose the backend token or OpenAI key
in client-side variables or frontend files. The relay only accepts the chat/status
routes, bounds body size, requires HTTPS in production, rejects upstream redirects,
streams the response without buffering and forwards cancellation. Its duration is
configured for 120 seconds. Vercel's deployment protection/rate controls can be used
when sharing a paid demo publicly; the Python app itself is not a per-user billing
or authentication system.

## Python backend

`Dockerfile` builds the API without embedding credentials, source HTML or model
weights in the image. It runs as a non-root user and accepts the platform's `PORT`.

Backend environment:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Hosted PostgreSQL connection, including provider-required TLS settings |
| `OPENAI_API_KEY` | Backend-only OpenAI credential |
| `OPENAI_MODEL` | Answer model, default `gpt-6-luna` |
| `RAG_API_TOKEN` | Same server-side token configured on Vercel |
| `RAG_MODEL_ROOT` | Model-cache root; image default `/app/data/models` |
| `RAG_ARTIFACT_ROOT` | BM25 snapshot root; image default `/app/data/indexes` |
| `RAG_THREADS` | ONNX CPU threads, default 4 |

Persist/mount the prepared `data/models` and `data/indexes` on the backend. Load
the matching document/chunk/vector/snapshot database, or rebuild it with the
existing migration/index commands against the hosted PostgreSQL. An empty hosted
database does not inherit the local Docker volume automatically. Indexing is an
offline job; do not run the crawler or rebuild BM25 per HTTP request.

`RAG_ARTIFACT_ROOT` resolves snapshots by ID rather than the indexer's original
absolute path, so Windows-created artifacts can be mounted in a Linux container.
The model and artifact checksums are still verified.

For a local all-container alternative, stop the existing Python preview first to
free port 8000, then run:

```powershell
docker compose --profile app up -d --build
```

The API and PostgreSQL ports bind to loopback only. For the direct local UI leave
`RAG_API_TOKEN` empty; a remote deployment must use the token and the Vercel relay.
Do not put the model or scraped corpus into Git to transfer them to hosting.

## Validation and limits

- Python tests cover streaming event order, bounded history, allowed message roles,
  source-only mode, provider failures and API token checks.
- Node tests cover relay streaming, method/body validation and credential separation.
- A live Greek contact query returned the published contact details with citation `[1]`.
- Browser automation was stopped by Computer Use because it could not establish
  the current Windows Chrome URL. Visual/mobile browser QA remains unverified.
- Cross-encoder reranking and a held-out answer-quality evaluation remain future work.
- The app bounds input/history/output and concurrent streams, but is not a complete
  public multi-tenant authentication, persistent conversation or rate-limiting service.

Primary references: [OpenAI streaming](https://developers.openai.com/api/docs/guides/streaming-responses),
[Vercel Node.js](https://vercel.com/docs/functions/runtimes/node-js),
[function limits](https://vercel.com/docs/functions/limitations),
[request cancellation](https://vercel.com/docs/functions/functions-api-reference).
