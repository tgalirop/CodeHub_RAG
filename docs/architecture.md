# Architecture and delivery plan

## 1. Inventory and extraction — implemented

The crawler starts at `https://codehub.gr/robots.txt`, follows its declared sitemaps,
and reads only URLs on the exact HTTPS site origin. `www.codehub.gr` is normalized
to the same origin. Tracking parameters are removed; other query-string page URLs
are excluded to avoid filtered listings and crawl traps. Robots restrictions are
checked before each content request, including redirects. Failure to obtain a
robots policy stops the run, except a 404 robots response permits crawling.

This milestone covers publicly accessible HTML. PDFs, media, other domains, form
submission and authenticated content are out of scope. Sitemap URLs and discovered
links are reported separately. A sitemap inventory is not a full-site coverage claim.
JavaScript-only content is not rendered; extraction flags and sample inspection
will determine whether a browser-rendering fallback is needed.

Artifacts preserve fetch timestamps, original HTML, canonical URLs, content hashes,
extractor and chunker versions. `lastmod` is source metadata, not proof of freshness.
Noindex responses are retained as raw evidence but excluded from retrieval chunks.
Two URLs with the same canonical target yield one document per crawl.

Taxonomy pages remain available for audit and link discovery but do not generate
retrieval chunks. The extractor restores Bricks animated counter values from their
explicit `countTo` source attributes; it does not execute JavaScript. It flags
malformed JSON-LD dates and possible visible-text/schema conflicts for manual
review, while retaining the original source values. These checks are heuristics,
not a general validation of every schema.org field. The document content hash also
covers title, description, language and structured data so metadata-only changes
produce a new version.

Chunks currently target 350 **whitespace-delimited words**, with 45 words of overlap
within the same section. These are not model token counts. Headings and titles are
prepended to `retrieval_text`; source URLs remain separate citation metadata. The
indexer re-splits these source chunks against the pinned embedding tokenizer before
creating vectors. Retrieval passages fit within 512 tokens including headings,
special tokens and the `passage: ` prefix. Nothing is silently truncated. Contact
details from the common footer are retained once on the Contact page.

## 2. Database loading and fresh content

- Implemented: checksum-tracked transactional migrations and an idempotent JSONL importer.
- Implemented: immutable document versions, per-run membership and current-page pointers;
  importing an older fetch does not roll back a newer page pointer.
- Implemented: embedding reuse by model identity and exact input hash, including
  reuse across metadata-only document versions and after interrupted builds.
- Planned: typed job/course/training filters beyond the current category filter.
- Planned: conditional HTTP requests and source retirement after complete crawls.
- An existing page is not proof that its job/training is active. Source status and
  dates remain evidence for the chat answer layer to interpret.

Database imports are transactions, while embedding batches are committed separately
so completed work can be reused after an interrupted index build. No pages are
automatically deleted or retired by the current importer.

## 3. Dense and lexical indexes

The initial local model is `intfloat/multilingual-e5-small`, pinned to revision
`614241f622f53c4eeff9890bdc4f31cfecc418b3`. It runs in ONNX Runtime on CPU with
mean pooling, L2 normalization and 384 dimensions. Explicit `query: ` and `passage: `
prefixes follow the model card. Downloaded model/tokenizer files are checksummed.
BGE-M3 and larger multilingual models remain candidates for a held-out comparison.

BM25 uses BM25S. PostgreSQL's built-in `ts_rank`
and `ts_rank_cd` are not used as BM25. The precomputed lexical index is saved on
persistent storage with tokenizer configuration, parameters, corpus hash,
chunk-position mapping and artifact checksums. `statistics.json` stores document
count, lengths, average length, document frequencies and IDF. Search sessions load
the saved index once with memory mapping; they never rebuild it per question.

Tokenization normalizes case/Greek accents, removes a small set of Greek/English
function words and preserves C#, C++, .NET, Node.js, Java and JavaScript as distinct
terms. A versioned, auditable bilingual glossary adds English aliases for Greek
domain concepts while retaining the original question. Both retrievers see the
expanded question. This supplements multilingual embeddings; it is not general
machine translation or a guarantee of synonym coverage.

## 4. Hybrid ranking and grounded answers

Dense retrieval uses exact pgvector cosine distance over members of one snapshot.
At this corpus size exact search avoids approximate-index recall tradeoffs. Category
filters apply before both retrievers select candidates. The default candidate pool
is 40 per retriever. RRF uses constant 60 and canonical pages, so different chunks
of the same page reinforce its ranking. Source passages are selected from the
ranked pages, with distinct pages prioritized before additional passages.

Cross-encoder reranking and model/candidate tuning on a held-out set remain planned.

Both retrievers use the same immutable retrieval snapshot. The next snapshot is
validated before the active pointer switches in one database transaction. Historical
vectors are filtered out by snapshot membership. Existing search sessions keep their
pinned snapshot until restarted; they do not mix new vectors with old BM25 files.

The current CLI returns passages, URLs, fetch timestamps and source warnings, not
generated answers. The implemented FastAPI chat layer streams OpenAI Responses
answers, with instructions to cite source IDs and acknowledge missing evidence.
Those instructions are not a guarantee of correctness. Retrieved webpage
text is untrusted reference material, never instructions to the assistant. Handle
follow-up questions using conversation context without losing named entities or
user filters. Display fetch dates for time-sensitive information.

## 5. Evaluation and interface

The checked-in 20-question positive smoke set covers services, training, jobs,
technical names and Greek/English paraphrases. Reports compare BM25, dense and
hybrid retrieval using page-level hit rate/Recall@5, MRR@5 and warm local latency.
This development set was used to identify contact extraction, fusion and glossary
improvements; it is not independent or held out. Negative questions and generated
answer correctness are not evaluated yet.

Next, create held-out Greek/English questions about services, training, jobs, eligibility,
dates and missing information. Compare dense-only, BM25-only and hybrid retrieval
using Recall@k/MRR, then assess citation correctness, unsupported answers, latency
and per-question cost. Include exact technical terms and plausible but unanswerable
questions. Keep some questions held out from tuning.

The implemented interface follows Code.Hub's inspected palette and original logo,
with source cards, suggested questions and streaming replies. It identifies itself
as an independent portfolio demo. Cards and chips display only known source IDs
cited in the answer text, including during streaming and when loading older saved
conversations. Citation-like text inside code examples is excluded. The UI numbers
citations consecutively by first mention, with matching labels in answer text,
source cards, chips and copied text. Raw evidence IDs remain unchanged in stored
messages and API results. The cloud API sends the final cited subset before completion.
The local preview is served by FastAPI.
The recommended cloud mode runs the complete chat API in Vercel Node.js, with
Neon PostgreSQL/pgvector and OpenAI query embeddings; no Python process or ONNX
model runs in the serverless function. The original container relay remains optional.

Cloud corpus embeddings use `text-embedding-3-small` at 384 dimensions. They live
in a separate `rag_cloud` schema and cannot be mixed with local E5 vectors.
The offline publisher stores N, average length, per-chunk lengths, DF/IDF and
Lucene BM25 term/chunk weights in PostgreSQL. Online search sums saved postings
for query terms and fuses them with exact cosine candidates at canonical-page level.
It never rebuilds the corpus index per request. Generated tokenizer/glossary JSON
and a fingerprint keep the Python publisher and Node runtime compatible.

Publication validates corpus hashes, embedding completeness and row counts before
atomically activating a snapshot. All search statements pin the same snapshot ID.
Durable SQL request reservations cap public demo API calls across serverless workers
and retain hashed address counters for two days; conversation history remains local
to the browser. These limits are not an exact spending cap or full user authentication.
The historical E5 development benchmark is not a benchmark for the new API model.
Cloud extraction retains each page's own content and removes trailing recommended
job/course cards. UI-only chunks are excluded, visible page titles are retained and
contact addresses keep their office/training-centre labels. The private `pages`
table stores checksummed parent text beside smaller embedding/BM25 chunks.
Search fuses up to 100 dense and 100 lexical chunk candidates at page level, applies
a soft inferred-category preference and expands the first 12 pages (16,000 characters
each). A contact page can supplement missing price/date questions, subject to the
same relevance check. Explicit UI category filters remain exclusive.

The cloud answer path first checks answerability with a strict structured verdict
and validates its source IDs. Unsupported questions receive fixed text; the free-form
answer generator sees only approved parent passages, ordered by usefulness. Their
IDs are assigned consecutively before streaming starts, preserving the same mapping
in generation and the UI. A relevant insufficient-evidence verdict permits one
bounded second batch; unrelated/injection-only questions do not. The check adds an API call and can
still make mistakes, so generated answers require evaluation against the source.
Free-text questions first pass through a model-based query planner with a strict
JSON schema (`web/lib/planner.js`). It interprets Greek, English, Greeklish, typos,
paraphrases and history, then returns search/list/count, a collection, a standalone
query, whether constraints exist, continuation intent and response language. No
phrase whitelist, edit-distance router or generated SQL is used. The model chooses
only bounded read-only application functions. Invalid/incomplete plans fail closed.

The server forces constrained or unsupported collection operations into retrieval,
so a filtered count cannot silently become the total for the whole catalogue.
Retrieval combines the original current question and the resolved query, retaining
technical names/negations while allowing the planner to resolve previous context.
The inferred collection is navigation context, not a blind exclusive search filter;
an explicit matching UI filter is honored. The evidence check sees the query plan
as context, never as factual evidence. Planning adds one metered model call per new
free-text question; validated next-page button actions bypass it. Token usage includes
the planner, evidence check and answer generation, but not query embeddings.

Unconstrained job/course counts use the stored catalogue's explicit total plus a
distinct-page SQL count. Generic Trainings refers to Training Programs courses;
scheduled events are distinct. Listings use unique URLs, sorted by title and URL,
ten per response, each with its own citation. Jobs also show posting references.
The bounded next-page offset and snapshot ID pin browsing to one version. Natural
language continuations use semantic intent and parse only the generated page range.
SQL counts/lists add no embedding or answer-generation calls after planning.
Qualified questions preserve technologies, cities, dates/status and other conditions
in retrieval; exact filtered totals are not inferred by counting the retrieved subset.
Job listings describe recorded pages without asserting current availability.

See deployment instructions for the provisioning steps and verification limits.

## Primary references

- [Code.Hub robots.txt](https://codehub.gr/robots.txt)
- [Code.Hub sitemaps](https://codehub.gr/sitemaps.xml)
- [pgvector](https://github.com/pgvector/pgvector)
- [BM25S persistence and retrieval](https://github.com/xhluca/bm25s)
- [BGE-M3 model card](https://huggingface.co/BAAI/bge-m3)
- [Multilingual E5-small model card](https://huggingface.co/intfloat/multilingual-e5-small)
- [FastEmbed](https://github.com/qdrant/fastembed)
- [PostgreSQL text search ranking](https://www.postgresql.org/docs/current/textsearch-controls.html)
- [Protego robots parser](https://github.com/scrapy/protego)
