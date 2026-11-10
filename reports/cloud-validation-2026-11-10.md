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

## Pending hosted verification

At the time of these checks, no Neon connection string was configured locally.
No new paid corpus embedding calls were made in this implementation run. The
synthetic test vectors exist only in the dedicated local `*_test` database.

The remaining steps are to configure the user's Neon URI and rotated OpenAI key,
run the real embedding/publication commands, add server-side Vercel variables,
deploy the new commit and verify a real answer through the hosted UI. The earlier
E5 evaluation numbers do not measure the new API embedding model. Browser visual
QA remains subject to the previously documented Computer Use limitation.
