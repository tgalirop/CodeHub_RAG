# Chatbot deployment

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

## Hosting layout

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

## Vercel project settings

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

No OpenAI key is needed in Vercel. Never expose the backend token or OpenAI key
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
