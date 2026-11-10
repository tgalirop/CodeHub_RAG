# Architecture and delivery plan

## 1. Inventory and extraction — current milestone

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
tokenizer budget will be measured after the embedding and generation models are chosen.

## 2. Database loading and fresh content — next milestone

- Add migrations and an idempotent JSONL importer for PostgreSQL.
- Preserve immutable versions while tracking each page's current version.
- Extract typed job/course/training fields from JSON-LD and inspected templates.
- Avoid inferring that an old course or job is active solely because its page exists.
- Add conditional requests and skip unchanged embeddings by content/model hash.
- Retire disappeared pages only after a successful, sufficiently complete crawl;
  a failed fetch must never be interpreted as evidence that a page was deleted.

The initial SQL includes the storage relationships but is not yet wired to the CLI.

## 3. Dense and lexical indexes

Evaluate a multilingual embedding model on Greek and English questions, including
Greek queries whose source content is English. BGE-M3 is a candidate, not a measured
winner. Embedding model identity, dimensions and preprocessing must be recorded.

Use a genuine BM25 implementation such as BM25S. PostgreSQL's built-in `ts_rank`
and `ts_rank_cd` must not be presented as BM25. Save the precomputed lexical index
on persistent storage with its tokenizer configuration, parameters, corpus hash,
chunk-position mapping and artifact checksum. Load once per worker or memory-map
the saved index. Corpus changes trigger a new build, never query-time rebuilding.

Evaluate Greek normalization, accents and English morphology while preserving
technical distinctions such as C#, C++, .NET, Java and JavaScript. Dense semantic
matching does not guarantee that every synonym or paraphrase will be retrieved.

## 4. Hybrid ranking and grounded answers

Fetch dense and lexical candidates independently, combine rankings with reciprocal
rank fusion, then evaluate a multilingual cross-encoder reranker. Tune candidate
counts and fusion settings on a labeled question set rather than selecting them
solely from examples that happen to work.

Keep both retrievers on the same immutable retrieval snapshot. Build and validate
the next snapshot before switching the active pointer atomically. Historical
vectors must not leak into current results: filter by snapshot membership.

Answers must cite source URLs and acknowledge missing evidence. Retrieved webpage
text is untrusted reference material, never instructions to the assistant. Handle
follow-up questions using conversation context without losing named entities or
user filters. Display fetch dates for time-sensitive information.

## 5. Evaluation and interface

Create labeled Greek/English questions about services, training, jobs, eligibility,
dates and missing information. Compare dense-only, BM25-only and hybrid retrieval
using Recall@k/MRR, then assess citation correctness, unsupported answers, latency
and per-question cost. Include exact technical terms and plausible but unanswerable
questions. Keep some questions held out from tuning.

The interface will follow the current Code.Hub visual identity using inspected
colors and original logo assets, with source cards and sample questions. Identify
it as an independent portfolio demo. The current milestone has no chat interface.

## Primary references

- [Code.Hub robots.txt](https://codehub.gr/robots.txt)
- [Code.Hub sitemaps](https://codehub.gr/sitemaps.xml)
- [pgvector](https://github.com/pgvector/pgvector)
- [BM25S persistence and retrieval](https://github.com/xhluca/bm25s)
- [BGE-M3 model card](https://huggingface.co/BAAI/bge-m3)
- [PostgreSQL text search ranking](https://www.postgresql.org/docs/current/textsearch-controls.html)
- [Protego robots parser](https://github.com/scrapy/protego)
