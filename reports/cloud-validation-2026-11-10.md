# Vercel / PostgreSQL cloud mode validation

Implementation target: personal demo on Vercel Hobby + Neon Free. This report
records local verification, not a successful remote deployment or a new retrieval
quality benchmark.

## Prepared corpus

- Exported the existing immutable E5 snapshot without modifying it.
- 167 canonical pages, 2,481 source chunks.
- 5,954 lexical terms and 105,299 sparse term/chunk postings.
- Average lexical chunk length: 55.8158 tokens after stopword removal.
- Cloud snapshot ID: `f6331cc23ddc3a1a0e20a00f52452d16a84bfe2ef458c2d7bac582db2fa34128`.
- Corpus export and embedding cache stay under ignored `data/cloud/`.
- Node/Python tokenization matched on all 2,481 actual passages and an additional
  case covering Greek sigma/accents, C#, C++, .NET, Node.js and Unicode normalization.

## Verified behavior

- All 49 Python tests passed with the dedicated PostgreSQL test database enabled.
- Ten Node unit/proxy tests passed; the optional database test was also run and
  passed separately against real PostgreSQL/pgvector with a synthetic corpus.
- Persisted cloud posting scores match the original BM25S Lucene formula.
- API embedding batches resume from a SQLite cache after interruption and avoid
  paying again for completed inputs. Provider response indices are checked.
- Corpus/configuration tampering and incomplete/invalid vectors are rejected.
- Database publication is idempotent and requires complete embeddings. Snapshot
  activation is transactional, with chunk/document/term/posting count checks.
- Actual Node/PostgreSQL queries return citation-ready passages, apply category
  filters and use a pinned snapshot for dense and lexical retrieval.
- SQL request reservations enforce durable hourly/global limits before API calls.
- Public database access is revoked and cloud tables enable row-level security.
- Mocked Responses streams preserve source/delta/done order, handle split UTF-8
  and CRLF, sanitize provider errors and reject incomplete streams.
- Client cancellation aborts in-flight provider requests.
- Ruff, shared configuration drift checks, frontend build and Git whitespace
  checks passed. Existing local E5/FastAPI behavior remains covered by its tests.

## Real Neon publication and API verification

The user configured a separate Neon pooled PostgreSQL database. TLS connectivity,
pgvector availability and access to both OpenAI models were verified without
printing credentials. The real corpus was then embedded and published:

- 2,470 unique embedding inputs for 2,481 chunks; duplicate inputs share cache entries.
- Initial corpus embedding usage: 242,272 input tokens, model `text-embedding-3-small`.
- Repeating `embed` created zero vectors, reused all 2,470 and consumed zero input tokens.
- Neon activation succeeded for the snapshot above, with 167 pages and 2,481 chunks.
- Total cloud table/index storage measured 56,057,856 bytes (about 53.5 MiB).
- The actual Node API, running locally against Neon and OpenAI, reported HTTP 200,
  `ready: true`, `answer_mode: openai`, and `backend: vercel-postgres`.
- A real Greek contact query returned the published email and phone with citation `[1]`.
- A short follow-up correctly retained the contact topic and cited the phone source.

The first unrelated-question smoke test exposed an unsupported general-knowledge
answer despite the prompt. The cloud answer path now requires a strict structured
evidence verdict before free-form generation. Verdict source IDs are validated;
only approved passages reach the generator. An unsupported verdict clears irrelevant
source cards and returns fixed localized text. Invalid/incomplete verdicts fail closed.
A repeated real unrelated-question test returned only the scope/evidence message,
without answering from world knowledge. Unit tests also cover unsupported verdicts,
invalid source IDs and exclusion of unapproved passages. The check adds a model
call and is still fallible; it does not guarantee factual accuracy.

The expanded Node suite passed 12 unit/proxy tests, in addition to the earlier
real PostgreSQL integration test. Existing Python tests and config/build checks pass.

## Cloud retrieval development smoke set

The existing 20-question development set was evaluated against the real Neon
corpus and API embeddings. This set was already used during local E5 development;
it is not independent or held out. No new tuning was applied to these results.

- Hybrid page hit@5: **18/20 (90%)**.
- Page MRR@5: **0.85**.
- Search-only median: about **467 ms** from this machine to Neon, excluding query
  embedding and answer generation; not directly comparable to local E5 latency.
- Misses: `en_rag_course` and `el_tom`.
- Evaluation embedding batch: 635 input tokens.

Full per-question results: [cloud retrieval smoke JSON](cloud-retrieval-smoke-2026-11-10.json).
The historical E5 metrics do not measure this new model, and these positive-query
retrieval metrics do not measure answer correctness or robustness.

## Remaining Vercel verification

Data publication and real Node/Neon/OpenAI calls are complete. The user must still
configure the server-side Vercel variables, deploy the current commit, and provide
the public frontend URL for verification through Vercel. A working local Node API
against hosted services does not establish that the public deployment is connected.
Browser visual QA remains subject to the previously documented Computer Use limitation.
