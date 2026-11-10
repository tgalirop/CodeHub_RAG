CREATE INDEX embedding_input_cache ON rag.embeddings(model, input_hash) WHERE input_hash IS NOT NULL;
