# Retrieval validation — 2026-11-10

## Implemented and run locally

- 542 source documents imported into PostgreSQL, with immutable historical versions.
- 2,481 active embedding passages from 167 eligible documents, within E5's 512-token budget.
- 384-dimensional multilingual E5-small vectors, pinned model revision and CPU inference.
- Exact pgvector cosine search, persisted BM25S, category filters and canonical-page RRF.
- Versioned bilingual domain expansion; original Greek query text is retained.
- BM25 artifacts include precomputed weights, vocabulary, document frequencies,
  IDF, document lengths and average length, with checksums and exact chunk mappings.

Active snapshot:
`f9476637e7037d6abe7e0c7424e3e0d756708959c247390a4f486684f0c8523f`.

## Persistence and consistency evidence

The first index computed 2,480 embeddings. After improving contact extraction,
the next snapshot reused those 2,480 inputs and computed only one new embedding.
Repeating the final index in a fresh process computed **zero** embeddings and
reused **2,481**, along with the existing BM25 artifact.

Integration tests cover duplicate imports, older imports not regressing page
versions, metadata-only changes reusing embeddings, snapshot isolation, and failed
or incomplete builds leaving the active snapshot unchanged. Unit tests reject
corrupt BM25 artifacts and forbid BM25 rebuilding during search.

Local checks passed: **33 unit tests and 6 PostgreSQL integration tests**, Ruff lint
and formatting, compilation, and a wheel build. The built wheel includes all three
numbered migrations and excludes local data, model weights and credentials.
The SQL vector/snapshot smoke test passed against the populated local database,
rolling back all test changes and preserving the active real snapshot.

## Retrieval smoke evaluation

The [20 questions](../evaluation/questions.jsonl) include Greek paraphrases and
English technical names. Each row labels one or more expected source URLs.
All three retrievers use the same glossary, category filter (where provided),
candidate count and five unique-page output limit.

| Mode | At least one expected source in top 5 | Mean labeled Recall@5 | MRR@5 | Warm p50 |
| --- | ---: | ---: | ---: | ---: |
| BM25 | 19/20 | 0.950 | 0.888 | 1.8 ms |
| Dense | 20/20 | 0.975 | 0.852 | 17.2 ms |
| Hybrid | 19/20 | 0.950 | 0.892 | 17.4 ms |

These timings exclude model/index startup and measure local CPU/PostgreSQL only.
Hybrid improves first-result ranking on average here, while dense finds a labeled
source for one more query at top 5. Hybrid is not uniformly better on every query.

This is a **development smoke set**, used while fixing extraction, page fusion and
query expansion. It is not a held-out benchmark, a production quality guarantee,
or a measurement of generated answers. The initial pre-improvement run and the
latest full per-question results are preserved:

- [Initial baseline](retrieval-baseline-2026-11-10.json)
- [Latest results and expanded queries](retrieval-smoke-2026-11-10.json)

## Remaining work

Held-out evaluation, cross-encoder reranking, better temporal/job filters, LLM
answer generation with citations, abstention, a search/chat API and the branded UI.
The current CLI returns real source passages. It does not generate chatbot answers.

Model reference: [multilingual E5-small](https://huggingface.co/intfloat/multilingual-e5-small).
