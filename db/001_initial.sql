-- Foundation for the next milestone. Ingestion currently writes portable JSONL.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS rag;

CREATE TABLE rag.crawl_runs (
    id text PRIMARY KEY,
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    manifest jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE rag.pages (
    id text PRIMARY KEY,
    canonical_url text UNIQUE NOT NULL,
    last_seen_at timestamptz NOT NULL,
    retired_at timestamptz
);

CREATE TABLE rag.document_versions (
    id text PRIMARY KEY,
    page_id text NOT NULL REFERENCES rag.pages(id),
    crawl_run_id text NOT NULL REFERENCES rag.crawl_runs(id),
    content_hash text NOT NULL,
    extractor_version text NOT NULL,
    title text NOT NULL,
    body text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}',
    raw_path text NOT NULL,
    fetched_at timestamptz NOT NULL,
    UNIQUE(page_id, content_hash, extractor_version)
);

CREATE TABLE rag.chunks (
    id text PRIMARY KEY,
    document_version_id text NOT NULL REFERENCES rag.document_versions(id),
    ordinal integer NOT NULL,
    body text NOT NULL,
    heading_path text[] NOT NULL,
    word_count integer NOT NULL,
    chunker_version text NOT NULL,
    UNIQUE(document_version_id, chunker_version, ordinal)
);

-- Dimension and ANN index are chosen after evaluating the embedding model.
CREATE TABLE rag.embeddings (
    chunk_id text NOT NULL REFERENCES rag.chunks(id),
    model text NOT NULL,
    dimensions integer NOT NULL CHECK(dimensions > 0),
    embedding vector NOT NULL,
    PRIMARY KEY(chunk_id, model),
    CHECK(vector_dims(embedding) = dimensions)
);

-- One immutable snapshot ties BM25 and dense retrieval to the same chunk set.
CREATE TABLE rag.retrieval_snapshots (
    id text PRIMARY KEY,
    corpus_hash text NOT NULL,
    embedding_model text NOT NULL,
    tokenizer_version text NOT NULL,
    bm25_parameters jsonb NOT NULL,
    bm25_artifact_path text NOT NULL,
    bm25_artifact_sha256 text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    active boolean NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX one_active_snapshot ON rag.retrieval_snapshots(active) WHERE active;
CREATE TABLE rag.snapshot_chunks (
    snapshot_id text NOT NULL REFERENCES rag.retrieval_snapshots(id),
    chunk_id text NOT NULL REFERENCES rag.chunks(id),
    bm25_position integer NOT NULL CHECK(bm25_position >= 0),
    PRIMARY KEY(snapshot_id, chunk_id),
    UNIQUE(snapshot_id, bm25_position)
);
