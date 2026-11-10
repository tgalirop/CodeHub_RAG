"""Resumable indexing, atomic snapshots and hybrid PostgreSQL/BM25 retrieval."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
from psycopg.types.json import Jsonb

from .database import import_run
from .embedding import file_hash, prepare_chunks, save_prepared
from .extract import digest
from .lexical import PARAMETERS, TOKENIZER_VERSION, LexicalIndex, build_artifact, verify_artifact
from .query import expand_query


def activate(connection, directory: Path, manifest: dict, chunks: list[dict]) -> str:
    if verify_artifact(directory) != manifest:
        raise ValueError("Artifact changed before activation")
    config = manifest["config"]
    snapshot_id = manifest["snapshot_id"]
    checksum = file_hash(directory / "manifest.json")
    expected = {item["id"]: digest(item["retrieval_text"]) for item in chunks}
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(752713642)")
        cursor.execute(
            """SELECT chunk_id,input_hash FROM rag.embeddings
            WHERE model=%s AND chunk_id=ANY(%s)""",
            (config["embedding_model"], list(expected)),
        )
        actual = {row["chunk_id"]: row["input_hash"] for row in cursor.fetchall()}
        if actual != expected:
            raise ValueError("Cannot activate snapshot: embeddings are missing or inputs differ")
        cursor.execute(
            """INSERT INTO rag.retrieval_snapshots(
            id,corpus_hash,embedding_model,tokenizer_version,bm25_parameters,
            bm25_artifact_path,bm25_artifact_sha256,manifest,ready)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,true) ON CONFLICT(id) DO NOTHING""",
            (
                snapshot_id,
                config["corpus_hash"],
                config["embedding_model"],
                TOKENIZER_VERSION,
                Jsonb(PARAMETERS),
                str(directory.resolve()),
                checksum,
                Jsonb(config),
            ),
        )
        cursor.execute("SELECT * FROM rag.retrieval_snapshots WHERE id=%s", (snapshot_id,))
        row = cursor.fetchone()
        if row["bm25_artifact_sha256"] != checksum or row["manifest"] != config or not row["ready"]:
            raise ValueError("Existing snapshot is inconsistent with this index")
        cursor.executemany(
            """INSERT INTO rag.snapshot_chunks(snapshot_id,chunk_id,bm25_position)
            VALUES(%s,%s,%s) ON CONFLICT DO NOTHING""",
            [(snapshot_id, item["id"], position) for position, item in enumerate(chunks)],
        )
        cursor.execute(
            """SELECT chunk_id FROM rag.snapshot_chunks WHERE snapshot_id=%s
            ORDER BY bm25_position""",
            (snapshot_id,),
        )
        if [row["chunk_id"] for row in cursor.fetchall()] != manifest["chunk_ids"]:
            raise ValueError("Snapshot chunk order differs from BM25 order")
        cursor.execute("UPDATE rag.retrieval_snapshots SET active=false WHERE active")
        cursor.execute("UPDATE rag.retrieval_snapshots SET active=true WHERE id=%s", (snapshot_id,))
    return snapshot_id


def build_index(
    connection, run: Path, embedder, artifact_root: Path = Path("data/indexes")
) -> dict:
    audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
    crawl = json.loads((run / "crawl.json").read_text(encoding="utf-8"))
    if not audit["inventory_complete"] or not crawl.get("crawl_complete") or crawl["errors"]:
        raise ValueError("Index activation requires a complete crawl without recorded errors")
    chunks = sorted(prepare_chunks(run, embedder), key=lambda item: item["id"])
    if not chunks:
        raise ValueError("No eligible chunks to index")
    prepared = save_prepared(run, chunks)
    imported = import_run(connection, run, chunks)
    config = {
        "corpus_hash": digest("\n".join(item["id"] for item in chunks)),
        "embedding_model": embedder.model_key,
        "dimensions": embedder.dimensions,
        "model_config": embedder.config,
        "tokenizer_version": TOKENIZER_VERSION,
        "bm25_parameters": PARAMETERS,
        "chunker_version": embedder.chunk_version,
    }
    snapshot_id = digest(json.dumps(config, sort_keys=True))
    with connection.transaction():
        connection.execute(
            """INSERT INTO rag.embedding_models(model,dimensions,config)
            VALUES(%s,%s,%s) ON CONFLICT(model) DO NOTHING""",
            (embedder.model_key, embedder.dimensions, Jsonb(embedder.config)),
        )
        registered = connection.execute(
            "SELECT * FROM rag.embedding_models WHERE model=%s", (embedder.model_key,)
        ).fetchone()
        if (
            registered["config"] != embedder.config
            or registered["dimensions"] != embedder.dimensions
        ):
            raise ValueError("Registered embedding model configuration changed")
    existing = connection.execute(
        """SELECT chunk_id,input_hash FROM rag.embeddings
        WHERE model=%s AND chunk_id=ANY(%s)""",
        (embedder.model_key, [c["id"] for c in chunks]),
    ).fetchall()
    cached = {row["chunk_id"]: row["input_hash"] for row in existing}
    missing = []
    for item in chunks:
        if item["id"] in cached:
            if cached[item["id"]] != digest(item["retrieval_text"]):
                raise ValueError("Cached embedding input hash mismatch")
        else:
            missing.append(item)
    reusable = (
        connection.execute(
            """SELECT DISTINCT ON(input_hash) input_hash,embedding
        FROM rag.embeddings WHERE model=%s AND input_hash=ANY(%s) ORDER BY input_hash,chunk_id""",
            (embedder.model_key, [digest(item["retrieval_text"]) for item in missing]),
        ).fetchall()
        if missing
        else []
    )
    by_input = {row["input_hash"]: row["embedding"] for row in reusable}
    copied = [item for item in missing if digest(item["retrieval_text"]) in by_input]
    if copied:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO rag.embeddings(
                chunk_id,model,dimensions,embedding,input_hash) VALUES(%s,%s,%s,%s,%s)
                ON CONFLICT(chunk_id,model) DO NOTHING""",
                [
                    (
                        item["id"],
                        embedder.model_key,
                        embedder.dimensions,
                        by_input[digest(item["retrieval_text"])],
                        digest(item["retrieval_text"]),
                    )
                    for item in copied
                ],
            )
    missing = [item for item in missing if digest(item["retrieval_text"]) not in by_input]
    reused_count = len(cached) + len(copied)
    for start in range(0, len(missing), 16):
        batch = missing[start : start + 16]
        vectors = embedder.documents([item["retrieval_text"] for item in batch])
        with connection.transaction(), connection.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO rag.embeddings(
                chunk_id,model,dimensions,embedding,input_hash) VALUES(%s,%s,%s,%s,%s)
                ON CONFLICT(chunk_id,model) DO NOTHING""",
                [
                    (
                        item["id"],
                        embedder.model_key,
                        embedder.dimensions,
                        vector,
                        digest(item["retrieval_text"]),
                    )
                    for item, vector in zip(batch, vectors, strict=True)
                ],
            )
        print(
            f"Embeddings {min(start + 16, len(missing))}/{len(missing)}; reused {reused_count}",
            flush=True,
        )
    directory, manifest = build_artifact(artifact_root, snapshot_id, chunks, config)
    activate(connection, directory, manifest, chunks)
    return {
        **imported,
        "snapshot_id": snapshot_id,
        "embedding_model": embedder.model_key,
        "dimensions": embedder.dimensions,
        "embeddings_created": len(missing),
        "embeddings_reused": reused_count,
        "bm25_artifact": str(directory),
        "prepared_chunks": str(prepared),
        "active": True,
    }


def reciprocal_rank_fusion(
    rankings: list[list[tuple[str, float]]], constant: int = 60
) -> list[tuple[str, float]]:
    if constant < 1:
        raise ValueError("RRF constant must be positive")
    scores: Counter = Counter()
    for ranking in rankings:
        seen = set()
        for rank, (key, _) in enumerate(ranking, 1):
            if key not in seen:
                scores[key] += 1 / (constant + rank)
                seen.add(key)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


class SearchEngine:
    """Load one immutable snapshot and BM25 index once per worker/session."""

    def __init__(self, connection, embedder, snapshot_id: str | None = None):
        self.connection = connection
        self.embedder = embedder
        if snapshot_id:
            row = connection.execute(
                "SELECT * FROM rag.retrieval_snapshots WHERE id=%s AND ready", (snapshot_id,)
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT * FROM rag.retrieval_snapshots WHERE active AND ready"
            ).fetchone()
        if not row:
            raise ValueError("No ready retrieval snapshot. Run index first.")
        if row["embedding_model"] != embedder.model_key:
            raise ValueError("Query model differs from snapshot model")
        self.snapshot_id = row["id"]
        self.lexical = LexicalIndex(Path(row["bm25_artifact_path"]), row["bm25_artifact_sha256"])
        if (
            self.lexical.manifest["snapshot_id"] != row["id"]
            or self.lexical.manifest["config"] != row["manifest"]
        ):
            raise ValueError("BM25 artifact differs from database snapshot configuration")
        rows = connection.execute(
            """SELECT c.id,c.body,c.heading_path,d.title,d.metadata,
            p.canonical_url AS url,d.fetched_at FROM rag.snapshot_chunks sc
            JOIN rag.chunks c ON c.id=sc.chunk_id
            JOIN rag.document_versions d ON d.id=c.document_version_id
            JOIN rag.pages p ON p.id=d.page_id
            WHERE sc.snapshot_id=%s ORDER BY sc.bm25_position""",
            (self.snapshot_id,),
        ).fetchall()
        if [row["id"] for row in rows] != self.lexical.chunk_ids:
            raise ValueError("Database and BM25 chunk mappings differ")
        self.metadata = {row["id"]: row for row in rows}

    def search(
        self,
        query: str,
        *,
        mode: str = "hybrid",
        limit: int = 5,
        candidates: int = 40,
        kind: str | None = None,
        per_page: int = 2,
    ) -> list[dict]:
        if mode not in {"hybrid", "dense", "bm25"} or not query.strip():
            raise ValueError("Provide a nonempty query and a valid retrieval mode")
        if limit < 1 or candidates < limit or per_page < 1:
            raise ValueError("Require candidates >= limit >= 1 and per_page >= 1")
        expanded, aliases = expand_query(query)
        while aliases and self.embedder.token_count(expanded, query=True) > 512:
            aliases.pop()
            expanded = query + "\n" + " ".join(aliases)
        mask = np.array(
            [
                float(kind is None or kind in self.metadata[key]["metadata"]["categories"])
                for key in self.lexical.chunk_ids
            ],
            dtype=np.float32,
        )
        lexical = self.lexical.search(expanded, candidates, mask) if mode != "dense" else []
        dense = []
        if mode != "bm25":
            vector = self.embedder.query(expanded)
            rows = self.connection.execute(
                """SELECT e.chunk_id,1-(e.embedding <=> %s) AS score
                FROM rag.embeddings e JOIN rag.snapshot_chunks sc ON sc.chunk_id=e.chunk_id
                JOIN rag.chunks c ON c.id=e.chunk_id
                JOIN rag.document_versions d ON d.id=c.document_version_id
                WHERE sc.snapshot_id=%s AND e.model=%s
                AND (%s::text IS NULL OR d.metadata->'categories' ? %s)
                ORDER BY e.embedding <=> %s,e.chunk_id LIMIT %s""",
                (vector, self.snapshot_id, self.embedder.model_key, kind, kind, vector, candidates),
            ).fetchall()
            dense = [(row["chunk_id"], float(row["score"])) for row in rows]

        def pages(ranking):
            unique = {}
            for key, score in ranking:
                unique.setdefault(self.metadata[key]["url"], score)
            return list(unique.items())

        page_ranking = (
            reciprocal_rank_fusion([pages(dense), pages(lexical)])
            if mode == "hybrid"
            else pages(dense or lexical)
        )
        chunk_ranking = (
            reciprocal_rank_fusion([dense, lexical]) if mode == "hybrid" else (dense or lexical)
        )
        grouped = {
            url: [(key, score) for key, score in chunk_ranking if self.metadata[key]["url"] == url]
            for url, _ in page_ranking
        }
        ranking = [
            (grouped[url][offset][0], score)
            for offset in range(per_page)
            for url, score in page_ranking
            if offset < len(grouped[url])
        ]
        dense_scores, lexical_scores = dict(dense), dict(lexical)
        page_counts: Counter = Counter()
        results = []
        for key, score in ranking:
            item = self.metadata[key]
            if page_counts[item["url"]] >= per_page:
                continue
            page_counts[item["url"]] += 1
            results.append(
                {
                    "rank": len(results) + 1,
                    "chunk_id": key,
                    "url": item["url"],
                    "title": item["title"],
                    "heading_path": item["heading_path"],
                    "text": item["body"],
                    "score": score,
                    "score_scope": "page",
                    "dense_score": dense_scores.get(key),
                    "bm25_score": lexical_scores.get(key),
                    "snapshot_id": self.snapshot_id,
                    "categories": item["metadata"]["categories"],
                    "fetched_at": item["fetched_at"].isoformat(),
                    "source_warnings": item["metadata"]
                    .get("quality", {})
                    .get("metadata_warnings", []),
                }
            )
            if len(results) == limit:
                break
        return results
