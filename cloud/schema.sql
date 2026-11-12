-- Standalone cloud store. Deliberately separate from the local E5 snapshot schema.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS rag_cloud;
SET LOCAL search_path = rag_cloud, extensions, public, pg_catalog;

CREATE TABLE IF NOT EXISTS rag_cloud.snapshots (
    id text PRIMARY KEY,
    config jsonb NOT NULL,
    statistics jsonb NOT NULL,
    documents integer NOT NULL CHECK (documents > 0),
    chunks integer NOT NULL CHECK (chunks > 0),
    ready boolean NOT NULL DEFAULT false,
    active boolean NOT NULL DEFAULT false CHECK (NOT active OR ready),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS one_cloud_snapshot ON rag_cloud.snapshots(active) WHERE active;
CREATE TABLE IF NOT EXISTS rag_cloud.chunks (
    snapshot_id text NOT NULL REFERENCES rag_cloud.snapshots(id) ON DELETE CASCADE,
    id text NOT NULL,
    url text NOT NULL,
    title text NOT NULL,
    body text NOT NULL,
    heading_path jsonb NOT NULL,
    categories text[] NOT NULL,
    warnings jsonb NOT NULL,
    fetched_at timestamptz NOT NULL,
    document_length integer NOT NULL CHECK (document_length > 0),
    input_hash text NOT NULL,
    embedding vector(384) NOT NULL,
    PRIMARY KEY (snapshot_id, id)
);
CREATE TABLE IF NOT EXISTS rag_cloud.terms (
    snapshot_id text NOT NULL REFERENCES rag_cloud.snapshots(id) ON DELETE CASCADE,
    term text NOT NULL,
    document_frequency integer NOT NULL,
    idf double precision NOT NULL,
    PRIMARY KEY(snapshot_id, term)
);
-- Clean parent documents let retrieval expand a matched passage without mixing
-- in navigation/recommendation cards or losing prerequisites at the page end.
CREATE TABLE IF NOT EXISTS rag_cloud.pages (
    snapshot_id text NOT NULL REFERENCES rag_cloud.snapshots(id) ON DELETE CASCADE,
    url text NOT NULL,
    title text NOT NULL,
    body text NOT NULL,
    categories text[] NOT NULL,
    warnings jsonb NOT NULL,
    fetched_at timestamptz NOT NULL,
    PRIMARY KEY(snapshot_id,url)
);
CREATE TABLE IF NOT EXISTS rag_cloud.postings (
    snapshot_id text NOT NULL,
    term text NOT NULL,
    chunk_id text NOT NULL,
    weight double precision NOT NULL CHECK (weight > 0),
    PRIMARY KEY (snapshot_id, term, chunk_id),
    FOREIGN KEY (snapshot_id, term) REFERENCES rag_cloud.terms(snapshot_id, term)
        ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id, chunk_id) REFERENCES rag_cloud.chunks(snapshot_id, id)
        ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS rag_cloud.usage (
    bucket text NOT NULL,
    period timestamptz NOT NULL,
    requests integer NOT NULL,
    PRIMARY KEY(bucket, period)
);
CREATE INDEX IF NOT EXISTS usage_expiry ON rag_cloud.usage(period);

-- Counts are durable across serverless instances; no raw IP addresses are stored.
CREATE OR REPLACE FUNCTION rag_cloud.reserve_request(
    client_hash text, daily_limit integer, hourly_limit integer
) RETURNS boolean LANGUAGE plpgsql SET search_path = pg_catalog, rag_cloud AS $$
DECLARE
    day_start timestamptz := date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    hour_start timestamptz := date_trunc('hour', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
BEGIN
    IF daily_limit < 1 OR hourly_limit < 1 THEN RETURN false; END IF;
    PERFORM pg_advisory_xact_lock(752713649);
    DELETE FROM rag_cloud.usage WHERE period < now() - interval '2 days';
    IF COALESCE((SELECT requests FROM rag_cloud.usage
        WHERE bucket='global' AND period=day_start),0) >= daily_limit
        OR COALESCE((SELECT requests FROM rag_cloud.usage
        WHERE bucket='ip:' || client_hash AND period=hour_start),0) >= hourly_limit
    THEN RETURN false; END IF;
    INSERT INTO rag_cloud.usage VALUES ('global', day_start, 1)
        ON CONFLICT(bucket,period) DO UPDATE SET requests=rag_cloud.usage.requests+1;
    INSERT INTO rag_cloud.usage VALUES ('ip:' || client_hash, hour_start, 1)
        ON CONFLICT(bucket,period) DO UPDATE SET requests=rag_cloud.usage.requests+1;
    RETURN true;
END $$;

-- Supabase's browser roles receive no access, including if this schema is exposed later.
REVOKE ALL ON SCHEMA rag_cloud FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA rag_cloud FROM PUBLIC;
REVOKE ALL ON FUNCTION rag_cloud.reserve_request(text,integer,integer) FROM PUBLIC;
ALTER TABLE rag_cloud.snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag_cloud.chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag_cloud.pages ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag_cloud.terms ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag_cloud.postings ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag_cloud.usage ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname='anon') THEN
        REVOKE ALL ON SCHEMA rag_cloud FROM anon;
        REVOKE ALL ON ALL TABLES IN SCHEMA rag_cloud FROM anon;
    END IF;
    IF EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated') THEN
        REVOKE ALL ON SCHEMA rag_cloud FROM authenticated;
        REVOKE ALL ON ALL TABLES IN SCHEMA rag_cloud FROM authenticated;
    END IF;
END $$;
