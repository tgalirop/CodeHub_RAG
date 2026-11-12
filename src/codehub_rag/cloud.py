"""Offline export, resumable API embeddings and atomic cloud PostgreSQL publication.

Run: uv run python -m codehub_rag.cloud {prepare,embed,publish,status}
Only embed calls OpenAI. Only publish writes the hosted database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .database import connect
from .extract import EXTRACTOR_VERSION, extract
from .extract import chunk as make_chunks
from .ingest import read_jsonl, write_json
from .lexical import STOPWORDS, TOKENIZER_VERSION, tokens
from .query import CONCEPTS, QUERY_VERSION
from .web import Resource

MODEL = "text-embedding-3-small"
DIMENSIONS = 384
PARAMETERS = {"k1": 1.5, "b": 0.75, "method": "lucene"}


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def lexical_config() -> dict:
    config = {
        "tokenizer_version": TOKENIZER_VERSION,
        "query_version": QUERY_VERSION,
        "stopwords": sorted(STOPWORDS),
        "concepts": [[list(roots), words] for roots, words in CONCEPTS],
    }
    return {**config, "fingerprint": digest(config)}


def corpus_statistics(chunks: list[dict]) -> tuple[dict, list[Counter], dict]:
    counts = [Counter(tokens(c["retrieval_text"])) for c in chunks]
    if not counts or any(not row for row in counts):
        raise ValueError("Cloud corpus requires nonempty tokenized chunks")
    frequencies = Counter(term for row in counts for term in row)
    n = len(counts)
    terms = {
        term: {"df": df, "idf": math.log(1 + (n - df + 0.5) / (df + 0.5))}
        for term, df in sorted(frequencies.items())
    }
    stats = {
        "document_count": n,
        "average_document_length": sum(sum(row.values()) for row in counts) / n,
        "vocabulary_size": len(terms),
        "postings": sum(len(row) for row in counts),
        "parameters": PARAMETERS,
    }
    return stats, counts, terms


def postings(chunks: list[dict], stats: dict, counts: list[Counter], terms: dict):
    for chunk, row in zip(chunks, counts, strict=True):
        norm = PARAMETERS["k1"] * (
            1
            - PARAMETERS["b"]
            + PARAMETERS["b"] * sum(row.values()) / stats["average_document_length"]
        )
        for term, tf in sorted(row.items()):
            # Same Lucene variant as bm25s: the constant k1+1 is omitted.
            yield term, chunk["id"], terms[term]["idf"] * tf / (tf + norm)


def prepare(connection, output: Path) -> dict:
    snapshot = connection.execute(
        "SELECT id FROM rag.retrieval_snapshots WHERE active AND ready"
    ).fetchone()
    if not snapshot:
        raise ValueError("Run the local index command first")
    rows = connection.execute(
        """SELECT c.id,c.body AS text,c.retrieval_text,c.heading_path,d.title,d.metadata,
        p.canonical_url AS url,d.fetched_at FROM rag.snapshot_chunks sc
        JOIN rag.chunks c ON c.id=sc.chunk_id
        JOIN rag.document_versions d ON d.id=c.document_version_id
        JOIN rag.pages p ON p.id=d.page_id WHERE sc.snapshot_id=%s ORDER BY c.id""",
        (snapshot["id"],),
    ).fetchall()
    chunks = [
        {
            "id": row["id"],
            "url": row["url"],
            "title": row["title"],
            "text": row["text"],
            "retrieval_text": row["retrieval_text"],
            "heading_path": row["heading_path"],
            "categories": row["metadata"]["categories"],
            "warnings": row["metadata"].get("quality", {}).get("metadata_warnings", []),
            "fetched_at": row["fetched_at"].isoformat(),
            "input_hash": digest(row["retrieval_text"]),
        }
        for row in rows
    ]
    statistics, _, _ = corpus_statistics(chunks)
    config = {
        "format": "cloud-v1",
        "model": MODEL,
        "dimensions": DIMENSIONS,
        "tokenizer_version": TOKENIZER_VERSION,
        "query_version": QUERY_VERSION,
        "lexical_config_hash": lexical_config()["fingerprint"],
        "bm25_parameters": PARAMETERS,
        "corpus_hash": digest(chunks),
    }
    bundle = {
        "snapshot_id": digest(config),
        "source_snapshot": snapshot["id"],
        "config": config,
        "statistics": statistics,
        "documents": len({c["url"] for c in chunks}),
        "chunks": chunks,
    }
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "corpus.json", bundle)
    return {"snapshot_id": bundle["snapshot_id"], "documents": bundle["documents"], **statistics}


def load_bundle(directory: Path) -> dict:
    bundle = json.loads((directory / "corpus.json").read_text(encoding="utf-8"))
    config = bundle["config"]
    if (
        config.get("format") != "cloud-v1"
        or config.get("tokenizer_version") != TOKENIZER_VERSION
        or config.get("query_version") != QUERY_VERSION
        or config.get("bm25_parameters") != PARAMETERS
        or config["model"] != MODEL
        or config["dimensions"] != DIMENSIONS
        or config["lexical_config_hash"] != lexical_config()["fingerprint"]
        or config["corpus_hash"] != digest(bundle["chunks"])
        or bundle["snapshot_id"] != digest(config)
    ):
        raise ValueError("Cloud corpus configuration/checksum mismatch; run prepare again")
    if len({c["id"] for c in bundle["chunks"]}) != len(bundle["chunks"]):
        raise ValueError("Duplicate cloud chunk IDs")
    if any(c["input_hash"] != digest(c["retrieval_text"]) for c in bundle["chunks"]):
        raise ValueError("Cloud embedding input hash mismatch")
    if bundle["statistics"] != corpus_statistics(bundle["chunks"])[0]:
        raise ValueError("Cloud statistics mismatch")
    if bundle["documents"] != len({c["url"] for c in bundle["chunks"]}):
        raise ValueError("Cloud document count mismatch")
    if config.get("parent_documents"):
        if config.get("pages_hash") != digest(bundle.get("pages", [])):
            raise ValueError("Parent document checksum mismatch")
        if {p["url"] for p in bundle["pages"]} != {c["url"] for c in bundle["chunks"]}:
            raise ValueError("Parent document coverage mismatch")
    return bundle


def prepare_run(run: Path, output: Path) -> dict:
    """Re-extract saved HTML into a new cloud bundle without changing the crawl."""
    audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
    crawl = json.loads((run / "crawl.json").read_text(encoding="utf-8"))
    if not audit["inventory_complete"] or not crawl.get("crawl_complete") or crawl["errors"]:
        raise ValueError("Preparation requires a complete crawl without recorded errors")
    chunks, pages = [], []
    for old in read_jsonl(run / "documents.jsonl"):
        raw = (run / old["raw_path"]).resolve()
        if not raw.is_relative_to(run.resolve()):
            raise ValueError("Raw path leaves crawl directory")
        doc = extract(
            Resource(
                old["url"], 200, raw.read_bytes(), "text/html", old.get("response_headers", {})
            ),
            old["categories"],
        )
        items = make_chunks(doc)
        substantive = [item for item in items if len(item["text"]) >= 40]
        if substantive:
            items = substantive
        if not items:
            continue
        parent = {
            "url": doc["canonical_url"],
            "title": doc["title"],
            "text": "\n\n".join(
                "\n".join([" > ".join(s["heading_path"]), *s["blocks"]]) for s in doc["sections"]
            ),
            "categories": doc["categories"],
            "warnings": doc["quality"]["metadata_warnings"],
            "fetched_at": old["fetched_at"],
        }
        pages.append(parent)
        for item in items:
            chunks.append(
                {
                    **item,
                    "categories": parent["categories"],
                    "warnings": parent["warnings"],
                    "fetched_at": parent["fetched_at"],
                    "input_hash": digest(item["retrieval_text"]),
                }
            )
    chunks.sort(key=lambda c: c["id"])
    pages.sort(key=lambda p: p["url"])
    config = {
        "format": "cloud-v1",
        "model": MODEL,
        "dimensions": DIMENSIONS,
        "tokenizer_version": TOKENIZER_VERSION,
        "query_version": QUERY_VERSION,
        "lexical_config_hash": lexical_config()["fingerprint"],
        "bm25_parameters": PARAMETERS,
        "corpus_hash": digest(chunks),
        "parent_documents": True,
        "pages_hash": digest(pages),
        "extractor_version": EXTRACTOR_VERSION,
    }
    bundle = {
        "snapshot_id": digest(config),
        "config": config,
        "statistics": corpus_statistics(chunks)[0],
        "documents": len(pages),
        "chunks": chunks,
        "pages": pages,
    }
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "corpus.json", bundle)
    return {
        "snapshot_id": bundle["snapshot_id"],
        "documents": len(pages),
        "chunks": len(chunks),
        "extractor_version": EXTRACTOR_VERSION,
    }


@contextmanager
def cache_open(directory: Path):
    db = sqlite3.connect(directory / "embeddings.sqlite3")
    db.execute("""CREATE TABLE IF NOT EXISTS embeddings (
        model text, dimensions integer, input_hash text, vector text,
        PRIMARY KEY(model,dimensions,input_hash))""")
    try:
        with db:
            yield db
    finally:
        db.close()


def valid_vector(vector) -> bool:
    return (
        isinstance(vector, list)
        and len(vector) == DIMENSIONS
        and all(isinstance(v, (float, int)) and math.isfinite(v) for v in vector)
        and sum(v * v for v in vector) > 0
    )


def cached_vectors(db) -> dict:
    values = {
        key: json.loads(vector)
        for key, vector in db.execute(
            "SELECT input_hash,vector FROM embeddings WHERE model=? AND dimensions=?",
            (MODEL, DIMENSIONS),
        )
    }
    if not all(valid_vector(vector) for vector in values.values()):
        raise ValueError("Invalid vector in local API embedding cache")
    return values


def embed_corpus(directory: Path, client) -> dict:
    bundle = load_bundle(directory)
    usage = 0
    created = 0
    with cache_open(directory) as cache:
        cached = cached_vectors(cache)
        unique = {c["input_hash"]: c["retrieval_text"] for c in bundle["chunks"]}
        missing = [(key, text) for key, text in unique.items() if key not in cached]
        for offset in range(0, len(missing), 32):
            batch = missing[offset : offset + 32]
            response = client.embeddings.create(
                model=MODEL, dimensions=DIMENSIONS, input=[text for _, text in batch]
            )
            ordered = sorted(response.data, key=lambda row: row.index)
            if [row.index for row in ordered] != list(range(len(batch))):
                raise ValueError("Embedding response indices differ from request")
            vectors = [row.embedding for row in ordered]
            if not all(valid_vector(vector) for vector in vectors):
                raise ValueError("Embedding API returned an invalid vector")
            cache.executemany(
                "INSERT OR REPLACE INTO embeddings VALUES(?,?,?,?)",
                [
                    (MODEL, DIMENSIONS, key, json.dumps(vector))
                    for (key, _), vector in zip(batch, vectors, strict=True)
                ],
            )
            cache.commit()  # A failure later never pays again for completed batches.
            usage += response.usage.total_tokens
            created += len(batch)
            print(f"API embeddings {created}/{len(missing)}; reused {len(unique) - len(missing)}")
    return {"created": created, "reused": len(unique) - len(missing), "input_tokens": usage}


def schema_path() -> Path:
    bundled = Path(__file__).parent / "cloud_sql" / "schema.sql"
    return bundled if bundled.exists() else Path(__file__).resolve().parents[2] / "cloud/schema.sql"


def publish(connection, directory: Path, *, activate: bool = True) -> dict:
    bundle = load_bundle(directory)
    chunks = bundle["chunks"]
    snapshot_id = bundle["snapshot_id"]
    with cache_open(directory) as cache:
        vectors = cached_vectors(cache)
    if any(c["input_hash"] not in vectors for c in chunks):
        raise ValueError("API embeddings missing. Run embed before publish.")
    statistics, counts, terms = corpus_statistics(chunks)
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(752713648)")
        connection.execute(schema_path().read_text(encoding="utf-8"), prepare=False)
        existing = connection.execute(
            "SELECT config,ready FROM rag_cloud.snapshots WHERE id=%s", (snapshot_id,)
        ).fetchone()
        if existing:
            if not existing["ready"] or existing["config"] != bundle["config"]:
                raise ValueError("Existing cloud snapshot is incomplete or inconsistent")
        else:
            connection.execute(
                """INSERT INTO rag_cloud.snapshots(id,config,statistics,documents,chunks)
                VALUES(%s,%s,%s,%s,%s)""",
                (
                    snapshot_id,
                    Jsonb(bundle["config"]),
                    Jsonb(statistics),
                    bundle["documents"],
                    len(chunks),
                ),
            )
            with connection.cursor() as cursor:
                with cursor.copy("COPY rag_cloud.chunks FROM STDIN") as copy:
                    for c, count in zip(chunks, counts, strict=True):
                        copy.write_row(
                            (
                                snapshot_id,
                                c["id"],
                                c["url"],
                                c["title"],
                                c["text"],
                                Jsonb(c["heading_path"]),
                                c["categories"],
                                Jsonb(c["warnings"]),
                                c["fetched_at"],
                                sum(count.values()),
                                c["input_hash"],
                                json.dumps(vectors[c["input_hash"]]),
                            )
                        )
                with cursor.copy("COPY rag_cloud.terms FROM STDIN") as copy:
                    for term, values in terms.items():
                        copy.write_row((snapshot_id, term, values["df"], values["idf"]))
                with cursor.copy("COPY rag_cloud.postings FROM STDIN") as copy:
                    for term, chunk_id, weight in postings(chunks, statistics, counts, terms):
                        copy.write_row((snapshot_id, term, chunk_id, weight))
                if bundle.get("pages"):
                    with cursor.copy("COPY rag_cloud.pages FROM STDIN") as copy:
                        for page in bundle["pages"]:
                            copy.write_row(
                                (
                                    snapshot_id,
                                    page["url"],
                                    page["title"],
                                    page["text"],
                                    page["categories"],
                                    Jsonb(page["warnings"]),
                                    page["fetched_at"],
                                )
                            )
        actual = connection.execute(
            """SELECT count(*) AS n,count(DISTINCT url) AS documents
            FROM rag_cloud.chunks WHERE snapshot_id=%s""",
            (snapshot_id,),
        ).fetchone()
        term_count = connection.execute(
            "SELECT count(*) AS n FROM rag_cloud.terms WHERE snapshot_id=%s", (snapshot_id,)
        ).fetchone()["n"]
        posting_count = connection.execute(
            "SELECT count(*) AS n FROM rag_cloud.postings WHERE snapshot_id=%s", (snapshot_id,)
        ).fetchone()["n"]
        if (
            actual["n"] != len(chunks)
            or actual["documents"] != bundle["documents"]
            or term_count != len(terms)
            or posting_count != statistics["postings"]
        ):
            raise ValueError("Cloud snapshot row counts differ from prepared corpus")
        if bundle.get("pages"):
            parent_count = connection.execute(
                "SELECT count(*) AS n FROM rag_cloud.pages WHERE snapshot_id=%s", (snapshot_id,)
            ).fetchone()["n"]
            if parent_count != bundle["documents"]:
                raise ValueError("Parent document count mismatch")
        if activate:
            connection.execute("UPDATE rag_cloud.snapshots SET active=false WHERE active")
        connection.execute(
            "UPDATE rag_cloud.snapshots SET ready=true,active=(active OR %s) WHERE id=%s",
            (activate, snapshot_id),
        )
    actual_active = connection.execute(
        "SELECT active FROM rag_cloud.snapshots WHERE id=%s", (snapshot_id,)
    ).fetchone()["active"]
    return {"snapshot_id": snapshot_id, "chunks": len(chunks), "active": actual_active}


def cloud_connect(settings: dict):
    url = settings.get("CLOUD_DATABASE_URL") or settings.get("SUPABASE_DATABASE_URL")
    if not url:
        raise ValueError("Set CLOUD_DATABASE_URL in the local .env, never in chat")
    # prepare_threshold=None works with transaction pooling without prepared statements.
    return psycopg.connect(
        url,
        sslmode="require",
        autocommit=True,
        row_factory=dict_row,
        connect_timeout=15,
        prepare_threshold=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "embed", "publish", "status"])
    parser.add_argument("--directory", type=Path, default=Path("data/cloud"))
    parser.add_argument("--run", type=Path, help="Prepare directly from saved crawl HTML")
    parser.add_argument("--stage", action="store_true", help="Publish a ready, inactive snapshot")
    args = parser.parse_args()
    settings = {**dotenv_values(".env"), **os.environ}
    try:
        if args.command == "prepare":
            if args.run:
                result = prepare_run(args.run, args.directory)
            else:
                with connect() as connection:
                    result = prepare(connection, args.directory)
        elif args.command == "embed":
            from openai import OpenAI

            if not settings.get("OPENAI_API_KEY"):
                raise ValueError("Set a valid OPENAI_API_KEY in .env")
            with OpenAI(api_key=settings["OPENAI_API_KEY"], timeout=60, max_retries=2) as client:
                result = embed_corpus(args.directory, client)
        else:
            with cloud_connect(settings) as connection:
                if args.command == "publish":
                    result = publish(connection, args.directory, activate=not args.stage)
                else:
                    row = connection.execute(
                        "SELECT id,documents,chunks,ready FROM rag_cloud.snapshots WHERE active"
                    ).fetchone()
                    result = dict(row) if row else {"ready": False}
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except ValueError as error:
        parser.exit(1, f"{error}\n")
    except Exception as error:
        # Connection/provider exceptions can contain credentials, hostnames or raw source text.
        parser.exit(
            1, f"Cloud operation failed ({type(error).__name__}). Check local configuration.\n"
        )


if __name__ == "__main__":
    main()
