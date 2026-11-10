"""Transactional migrations and idempotent imports into PostgreSQL/pgvector."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .embedding import file_hash
from .ingest import read_jsonl


def connect(*, register: bool = True):
    settings = {**dotenv_values(Path.cwd() / ".env"), **os.environ}
    if settings.get("DATABASE_URL"):
        connection = psycopg.connect(
            settings["DATABASE_URL"],
            autocommit=True,
            row_factory=dict_row,
            connect_timeout=10,
        )
    else:
        connection = psycopg.connect(
            host=settings.get("POSTGRES_HOST", "127.0.0.1"),
            port=int(settings.get("POSTGRES_PORT", "5432")),
            dbname=settings.get("POSTGRES_DB", "codehub_rag"),
            user=settings.get("POSTGRES_USER", "codehub"),
            password=settings.get("POSTGRES_PASSWORD", ""),
            autocommit=True,
            row_factory=dict_row,
            connect_timeout=10,
        )
    try:
        if register:
            register_vector(connection)
        return connection
    except Exception:
        connection.close()
        raise


def migrate(connection) -> list[str]:
    directory = Path(__file__).parent / "sql"
    if not directory.exists():
        directory = Path(__file__).resolve().parents[2] / "db"
    applied = []
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(752713640)")
        connection.execute("CREATE SCHEMA IF NOT EXISTS rag")
        connection.execute("""CREATE TABLE IF NOT EXISTS rag.schema_migrations(
            version text PRIMARY KEY, sha256 text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now())""")
        for path in sorted(directory.glob("[0-9][0-9][0-9]_*.sql")):
            checksum = file_hash(path)
            row = connection.execute(
                "SELECT sha256 FROM rag.schema_migrations WHERE version=%s",
                (path.name,),
            ).fetchone()
            if row:
                if row["sha256"] != checksum:
                    raise ValueError(f"Applied migration changed: {path.name}")
                continue
            existing = connection.execute("SELECT to_regclass('rag.crawl_runs') AS name").fetchone()
            if path.name.startswith("001_") and existing["name"]:
                required = (
                    "pages",
                    "document_versions",
                    "chunks",
                    "embeddings",
                    "retrieval_snapshots",
                    "snapshot_chunks",
                )
                for table in required:
                    if not connection.execute(
                        "SELECT to_regclass(%s) AS name", (f"rag.{table}",)
                    ).fetchone()["name"]:
                        raise ValueError("Incomplete legacy schema; cannot adopt migration 001")
            else:
                connection.execute(path.read_text(encoding="utf-8"), prepare=False)
            connection.execute(
                "INSERT INTO rag.schema_migrations(version,sha256) VALUES(%s,%s)",
                (path.name, checksum),
            )
            applied.append(path.name)
    return applied


def import_run(connection, run: Path, chunks: list[dict] | None = None) -> dict:
    import json

    documents = read_jsonl(run / "documents.jsonl")
    chunks = read_jsonl(run / "chunks.jsonl") if chunks is None else chunks
    if not documents:
        raise ValueError("Cannot import an empty corpus")
    by_id = {document["id"]: document for document in documents}
    if len(by_id) != len(documents) or len({item["id"] for item in chunks}) != len(chunks):
        raise ValueError("Duplicate document or chunk IDs")
    for item in chunks:
        document = by_id.get(item["document_version_id"])
        if not document or not document["retrieval_eligible"] or document["noindex"]:
            raise ValueError("A chunk refers to an unknown or excluded document")
    audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
    crawl = json.loads((run / "crawl.json").read_text(encoding="utf-8"))
    run_id = run.name
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(752713641)")
        cursor.execute(
            """INSERT INTO rag.crawl_runs(id,started_at,completed_at,manifest)
            VALUES(%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET manifest=EXCLUDED.manifest""",
            (
                run_id,
                audit["started_at"],
                crawl["completed_at"],
                Jsonb({"audit": audit, "crawl": crawl}),
            ),
        )
        cursor.executemany(
            """INSERT INTO rag.pages(id,canonical_url,last_seen_at)
            VALUES(%s,%s,%s) ON CONFLICT(id) DO UPDATE SET
            last_seen_at=GREATEST(rag.pages.last_seen_at,EXCLUDED.last_seen_at)""",
            [(doc["page_id"], doc["canonical_url"], doc["fetched_at"]) for doc in documents],
        )
        cursor.executemany(
            """INSERT INTO rag.document_versions(
            id,page_id,crawl_run_id,content_hash,extractor_version,title,body,metadata,raw_path,fetched_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
            [
                (
                    doc["id"],
                    doc["page_id"],
                    run_id,
                    doc["content_hash"],
                    doc["extractor_version"],
                    doc["title"],
                    doc["text"],
                    Jsonb(
                        {
                            key: doc.get(key)
                            for key in (
                                "description",
                                "language",
                                "categories",
                                "structured_data",
                                "quality",
                                "retrieval_eligible",
                                "sitemap_lastmod",
                                "url",
                            )
                        }
                    ),
                    str((run / doc["raw_path"]).resolve()),
                    doc["fetched_at"],
                )
                for doc in documents
            ],
        )
        cursor.executemany(
            """UPDATE rag.pages SET current_version_id=%s
            WHERE id=%s AND last_seen_at <= %s::timestamptz""",
            [(doc["id"], doc["page_id"], doc["fetched_at"]) for doc in documents],
        )
        cursor.executemany(
            """INSERT INTO rag.crawl_run_documents VALUES(%s,%s)
            ON CONFLICT DO NOTHING""",
            [(run_id, doc["id"]) for doc in documents],
        )
        cursor.executemany(
            """INSERT INTO rag.chunks(
            id,document_version_id,ordinal,body,heading_path,word_count,chunker_version,retrieval_text,metadata)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
            [
                (
                    item["id"],
                    item["document_version_id"],
                    item["ordinal"],
                    item["text"],
                    item["heading_path"],
                    item["word_count"],
                    item["chunker_version"],
                    item["retrieval_text"],
                    Jsonb(
                        {
                            key: item.get(key)
                            for key in (
                                "source_chunk_id",
                                "embedding_tokens",
                            )
                        }
                    ),
                )
                for item in chunks
            ],
        )
        cursor.executemany(
            """INSERT INTO rag.crawl_run_chunks VALUES(%s,%s)
            ON CONFLICT DO NOTHING""",
            [(run_id, item["id"]) for item in chunks],
        )
    return {"run": run_id, "documents": len(documents), "chunks": len(chunks)}
