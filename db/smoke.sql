-- Exercise real extension behavior and storage invariants; persist no test rows.
\set ON_ERROR_STOP on
BEGIN;
UPDATE rag.retrieval_snapshots SET active=false WHERE active;
INSERT INTO rag.embedding_models(model,dimensions,config)
VALUES ('schema-test',3,'{}');
SELECT extversion AS pgvector_version FROM pg_extension WHERE extname = 'vector';
INSERT INTO rag.crawl_runs(id, started_at) VALUES ('__smoke__', now());
INSERT INTO rag.pages(id, canonical_url, last_seen_at)
VALUES ('__smoke__', 'https://codehub.gr/__schema_test__/', now());
INSERT INTO rag.document_versions(
    id, page_id, crawl_run_id, content_hash, extractor_version, title, body, raw_path, fetched_at
) VALUES ('__smoke__', '__smoke__', '__smoke__', 'hash', 'test', 'Test', 'Test', 'raw/test', now());
INSERT INTO rag.chunks(
    id, document_version_id, ordinal, body, heading_path, word_count, chunker_version
) VALUES ('__smoke__', '__smoke__', 0, 'Test', ARRAY['Test'], 1, 'test');
INSERT INTO rag.embeddings(chunk_id, model, dimensions, embedding)
VALUES ('__smoke__', 'schema-test', 3, '[1,0,0]');

DO $$
BEGIN
    IF (SELECT embedding <=> '[1,0,0]'::vector FROM rag.embeddings
        WHERE chunk_id = '__smoke__' AND model = 'schema-test') <> 0 THEN
        RAISE EXCEPTION 'Unexpected cosine distance';
    END IF;
    BEGIN
        INSERT INTO rag.embeddings(chunk_id, model, dimensions, embedding)
        VALUES ('__smoke__', 'bad-dimension', 2, '[1,0,0]');
        RAISE EXCEPTION 'Dimension mismatch was accepted';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
END $$;

INSERT INTO rag.retrieval_snapshots(
    id, corpus_hash, embedding_model, tokenizer_version, bm25_parameters,
    bm25_artifact_path, bm25_artifact_sha256, active, ready
) VALUES ('__smoke__', 'hash', 'schema-test', 'test', '{}', 'test', 'hash', true, true);
INSERT INTO rag.snapshot_chunks(snapshot_id, chunk_id, bm25_position)
VALUES ('__smoke__', '__smoke__', 0);

DO $$
BEGIN
    BEGIN
        INSERT INTO rag.retrieval_snapshots(
            id, corpus_hash, embedding_model, tokenizer_version, bm25_parameters,
            bm25_artifact_path, bm25_artifact_sha256, active, ready
        ) VALUES ('__smoke_other__', 'hash', 'schema-test', 'test', '{}', 'test', 'hash', true, true);
        RAISE EXCEPTION 'Two active snapshots were accepted';
    EXCEPTION WHEN unique_violation THEN
        NULL;
    END;
END $$;
ROLLBACK;
