import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from pgvector.psycopg import register_vector
from test_retrieval import FakeEmbedder

from codehub_rag.database import connect, import_run, migrate
from codehub_rag.extract import chunk, extract
from codehub_rag.ingest import write_json, write_jsonl
from codehub_rag.lexical import build_artifact
from codehub_rag.retrieval import SearchEngine, activate, build_index
from codehub_rag.web import Resource


@pytest.fixture
def database():
    if os.getenv("CODEHUB_TEST_DB") != "1":
        pytest.skip("Set CODEHUB_TEST_DB=1 and connect to a dedicated *_test database")
    with connect(register=False) as connection:
        name = connection.execute("SELECT current_database() AS name").fetchone()["name"]
        if not name.endswith("_test"):
            pytest.fail("Database tests require a dedicated database name ending in _test")
        migrate(connection)
        register_vector(connection)
        connection.execute("BEGIN")
        try:
            yield connection
        finally:
            connection.execute("ROLLBACK")


def make_run(directory, marker="alpha", *, newer=0, language="en"):
    directory.mkdir()
    (directory / "raw").mkdir()
    documents = []
    chunks = []
    for slug, text, category in [
        ("training", f"Training {marker} for software engineers and corporate teams.", "course"),
        ("java-job", f"Java {marker} Spring developer role in Athens.", "job"),
    ]:
        html = (
            f'<html lang="{language}"><title>{slug} {marker}</title>'
            f"<main><h1>{slug}</h1><p>{text}</p></main></html>"
        )
        doc = extract(
            Resource(f"https://codehub.gr/{slug}/", 200, html.encode(), "text/html", {}), [category]
        )
        doc["fetched_at"] = (datetime(2026, 11, 10, tzinfo=UTC) + timedelta(days=newer)).isoformat()
        doc["raw_path"] = f"raw/{slug}.html"
        (directory / doc["raw_path"]).write_text(html, encoding="utf-8")
        documents.append(doc)
        chunks.extend(chunk(doc))
    write_jsonl(directory / "documents.jsonl", documents)
    write_jsonl(directory / "chunks.jsonl", chunks)
    write_json(
        directory / "audit.json",
        {"started_at": documents[0]["fetched_at"], "inventory_complete": True},
    )
    write_json(
        directory / "crawl.json",
        {
            "completed_at": documents[0]["fetched_at"],
            "crawl_complete": True,
            "errors": [],
        },
    )
    return directory


def test_migrations_and_import_are_idempotent_and_do_not_regress_current_version(
    database, tmp_path
):
    assert migrate(database) == []
    older = make_run(tmp_path / "older")
    newer = make_run(tmp_path / "newer", "beta", newer=1)
    import_run(database, older)
    import_run(database, older)
    assert database.execute("SELECT count(*) AS n FROM rag.document_versions").fetchone()["n"] == 2
    import_run(database, newer)
    import_run(database, older)
    rows = database.execute("""SELECT d.title FROM rag.pages p
        JOIN rag.document_versions d ON d.id=p.current_version_id""").fetchall()
    assert all("beta" in row["title"] for row in rows)


def test_embedding_cache_and_loaded_bm25_are_reused(database, tmp_path, monkeypatch):
    run = make_run(tmp_path / "run")
    embedder = FakeEmbedder()
    first = build_index(database, run, embedder, tmp_path / "indexes")
    assert first["embeddings_created"] == 2
    second = build_index(database, run, embedder, tmp_path / "indexes")
    assert first["snapshot_id"] == second["snapshot_id"]
    assert second["embeddings_created"] == 0 and second["embeddings_reused"] == 2
    assert embedder.document_calls == 2
    engine = SearchEngine(database, embedder)
    import bm25s

    monkeypatch.setattr(bm25s.BM25, "index", lambda *a, **kw: pytest.fail("Query rebuilt BM25"))
    assert engine.search("εκπαίδευση", mode="dense")[0]["url"].endswith("/training/")
    assert engine.search("Java", kind="job")[0]["categories"] == ["job"]
    assert engine.search("Java", kind="course", mode="bm25") == []


def test_snapshot_switch_does_not_mix_versions_and_failed_activation_keeps_old(database, tmp_path):
    embedder = FakeEmbedder()
    first = build_index(database, make_run(tmp_path / "a"), embedder, tmp_path / "indexes")
    old_engine = SearchEngine(database, embedder)
    second = build_index(
        database, make_run(tmp_path / "b", "beta", newer=1), embedder, tmp_path / "indexes"
    )
    new_engine = SearchEngine(database, embedder)
    assert old_engine.snapshot_id == first["snapshot_id"]
    assert new_engine.snapshot_id == second["snapshot_id"]
    assert all("alpha" in row["title"] for row in old_engine.search("training"))
    assert all("beta" in row["title"] for row in new_engine.search("training"))
    manifest = json.loads(
        (tmp_path / "indexes" / second["snapshot_id"] / "manifest.json").read_text()
    )
    fake_chunk = {"id": "missing-vector", "retrieval_text": "training without an embedding"}
    directory, bad_manifest = build_artifact(
        tmp_path / "indexes", "not-ready", [fake_chunk], manifest["config"]
    )
    with pytest.raises(ValueError, match="embeddings are missing"):
        activate(database, directory, bad_manifest, [fake_chunk])
    current = database.execute("SELECT id FROM rag.retrieval_snapshots WHERE active").fetchone()
    assert current["id"] == second["snapshot_id"]


def test_incomplete_crawl_cannot_be_activated(database, tmp_path):
    run = make_run(tmp_path / "partial")
    write_json(
        run / "crawl.json", {"completed_at": "2026-11-10", "crawl_complete": False, "errors": []}
    )
    with pytest.raises(ValueError, match="complete crawl"):
        build_index(database, run, FakeEmbedder(), tmp_path / "indexes")
    assert (
        database.execute("SELECT count(*) AS n FROM rag.retrieval_snapshots").fetchone()["n"] == 0
    )


def test_metadata_only_versions_reuse_embedding_inputs(database, tmp_path):
    embedder = FakeEmbedder()
    first_run = make_run(tmp_path / "original", language="en")
    second_run = make_run(tmp_path / "metadata-change", language="el", newer=1)
    build_index(database, first_run, embedder, tmp_path / "indexes")
    result = build_index(database, second_run, embedder, tmp_path / "indexes")
    assert result["embeddings_created"] == 0
    assert result["embeddings_reused"] == 2
    assert embedder.document_calls == 2
