ALTER TABLE rag.pages ADD COLUMN current_version_id text REFERENCES rag.document_versions(id);
ALTER TABLE rag.chunks ADD COLUMN retrieval_text text NOT NULL DEFAULT '';
ALTER TABLE rag.chunks ADD COLUMN metadata jsonb NOT NULL DEFAULT '{}';
ALTER TABLE rag.embeddings ADD COLUMN input_hash text;

CREATE TABLE rag.embedding_models (
    model text PRIMARY KEY,
    dimensions integer NOT NULL CHECK(dimensions > 0),
    config jsonb NOT NULL,
    UNIQUE(model, dimensions)
);
ALTER TABLE rag.embeddings ADD CONSTRAINT registered_embedding_model
    FOREIGN KEY(model, dimensions) REFERENCES rag.embedding_models(model, dimensions);

CREATE TABLE rag.crawl_run_documents (
    crawl_run_id text NOT NULL REFERENCES rag.crawl_runs(id),
    document_version_id text NOT NULL REFERENCES rag.document_versions(id),
    PRIMARY KEY(crawl_run_id, document_version_id)
);
CREATE TABLE rag.crawl_run_chunks (
    crawl_run_id text NOT NULL REFERENCES rag.crawl_runs(id),
    chunk_id text NOT NULL REFERENCES rag.chunks(id),
    PRIMARY KEY(crawl_run_id, chunk_id)
);
ALTER TABLE rag.retrieval_snapshots ADD COLUMN manifest jsonb NOT NULL DEFAULT '{}';
ALTER TABLE rag.retrieval_snapshots ADD COLUMN ready boolean NOT NULL DEFAULT false;
ALTER TABLE rag.retrieval_snapshots ADD CONSTRAINT active_snapshot_is_ready CHECK(NOT active OR ready);
CREATE INDEX snapshot_chunk_lookup ON rag.snapshot_chunks(chunk_id, snapshot_id);
CREATE INDEX embeddings_model_lookup ON rag.embeddings(model);
