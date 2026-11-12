from types import SimpleNamespace

import bm25s
import pytest

from codehub_rag.cloud import (
    DIMENSIONS,
    MODEL,
    PARAMETERS,
    cache_open,
    cached_vectors,
    corpus_statistics,
    digest,
    embed_corpus,
    lexical_config,
    load_bundle,
    postings,
    publish,
)
from codehub_rag.ingest import write_json
from codehub_rag.lexical import TOKENIZER_VERSION, tokens
from codehub_rag.query import QUERY_VERSION


def make_bundle(directory, n=3):
    directory.mkdir(exist_ok=True, parents=True)
    chunks = [
        {
            "id": str(i),
            "url": f"https://codehub.gr/{i}/",
            "title": f"Page {i}",
            "text": f"Training Java C# εκπαίδευση contact phone example{i}",
            "retrieval_text": f"Training Java C# εκπαίδευση contact phone example{i}",
            "heading_path": ["Details"],
            "categories": ["course" if i % 2 else "job"],
            "warnings": [],
            "fetched_at": "2026-11-10T12:00:00+00:00",
        }
        for i in range(n)
    ]
    for c in chunks:
        c["input_hash"] = digest(c["retrieval_text"])
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
        "config": config,
        "statistics": corpus_statistics(chunks)[0],
        "documents": n,
        "chunks": chunks,
    }
    write_json(directory / "corpus.json", bundle)
    return bundle


class FakeAPI:
    def __init__(self, fail_after=None):
        self.embeddings = self
        self.batches = []
        self.fail_after = fail_after

    def create(self, *, model, dimensions, input):
        assert (model, dimensions) == (MODEL, DIMENSIONS)
        if len(self.batches) == self.fail_after:
            raise RuntimeError("interrupted batch")
        self.batches.append(input)
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=i, embedding=[1.0, *([0.0] * (DIMENSIONS - 1))])
                for i in reversed(range(len(input)))
            ],
            usage=SimpleNamespace(total_tokens=10 * len(input)),
        )


def test_persisted_posting_weights_match_existing_bm25s():
    chunks = [
        {"id": str(i), "retrieval_text": text}
        for i, text in enumerate(
            [
                "Java Java Spring developer",
                "JavaScript developer",
                "C# .NET εκπαίδευση",
            ]
        )
    ]
    stats, counts, terms = corpus_statistics(chunks)
    weights = {(key, term): weight for term, key, weight in postings(chunks, stats, counts, terms)}
    bm = bm25s.BM25(**PARAMETERS)
    bm.index([tokens(c["retrieval_text"]) for c in chunks], show_progress=False)
    indices, scores = bm.retrieve([tokens("Java developer")], k=3, show_progress=False)
    for index, score in zip(indices[0], scores[0], strict=True):
        expected = sum(weights.get((str(index), term), 0) for term in ["java", "developer"])
        assert float(score) == pytest.approx(expected, abs=1e-6)


def test_embedding_batches_resume_without_repaying_completed_inputs(tmp_path):
    make_bundle(tmp_path, n=35)
    interrupted = FakeAPI(fail_after=1)
    with pytest.raises(RuntimeError):
        embed_corpus(tmp_path, interrupted)
    with cache_open(tmp_path) as cache:
        assert len(cached_vectors(cache)) == 32
    resumed = FakeAPI()
    result = embed_corpus(tmp_path, resumed)
    assert result == {"created": 3, "reused": 32, "input_tokens": 30}
    assert len(resumed.batches) == 1
    assert embed_corpus(tmp_path, FakeAPI())["created"] == 0


def test_corpus_tampering_and_invalid_cache_are_rejected(tmp_path):
    bundle = make_bundle(tmp_path)
    bundle["chunks"][0]["text"] = "tampered source"
    write_json(tmp_path / "corpus.json", bundle)
    with pytest.raises(ValueError, match="checksum"):
        load_bundle(tmp_path)
    with cache_open(tmp_path) as cache:
        cache.execute("INSERT INTO embeddings VALUES(?,?,?,?)", (MODEL, DIMENSIONS, "bad", "[0]"))
        with pytest.raises(ValueError, match="Invalid vector"):
            cached_vectors(cache)


def test_cloud_publication_atomicity_and_durable_limits(database, tmp_path):
    bundle = make_bundle(tmp_path)
    # No partial schema/snapshot is created when embeddings are missing.
    with pytest.raises(ValueError, match="missing"):
        publish(database, tmp_path)
    embed_corpus(tmp_path, FakeAPI())
    first = publish(database, tmp_path)
    database.execute("DELETE FROM rag_cloud.usage")
    assert publish(database, tmp_path) == first
    assert publish(database, tmp_path, activate=False) == first
    assert (
        database.execute("SELECT count(*) AS n FROM rag_cloud.snapshots WHERE active").fetchone()[
            "n"
        ]
        == 1
    )
    assert (
        database.execute(
            "SELECT count(*) AS n FROM rag_cloud.chunks WHERE snapshot_id=%s",
            (first["snapshot_id"],),
        ).fetchone()["n"]
        == 3
    )
    assert (
        database.execute(
            "SELECT count(*) AS n FROM rag_cloud.postings WHERE snapshot_id=%s",
            (first["snapshot_id"],),
        ).fetchone()["n"]
        == bundle["statistics"]["postings"]
    )
    row = database.execute("SELECT config FROM rag_cloud.snapshots WHERE active").fetchone()
    assert row["config"]["model"] == MODEL
    assert database.execute("SELECT rag_cloud.reserve_request('one',3,1) AS ok").fetchone()["ok"]
    assert not database.execute("SELECT rag_cloud.reserve_request('one',3,1) AS ok").fetchone()[
        "ok"
    ]
    assert database.execute("SELECT rag_cloud.reserve_request('two',3,1) AS ok").fetchone()["ok"]
    assert database.execute("SELECT rag_cloud.reserve_request('three',3,1) AS ok").fetchone()["ok"]
    assert not database.execute("SELECT rag_cloud.reserve_request('four',3,1) AS ok").fetchone()[
        "ok"
    ]
    assert database.execute(
        "SELECT bool_and(relrowsecurity) AS ok FROM pg_class "
        "WHERE relnamespace='rag_cloud'::regnamespace AND relkind='r'"
    ).fetchone()["ok"]


def test_parent_documents_staged_publication_and_checksums(database, tmp_path):
    import copy

    original = make_bundle(tmp_path)
    embed_corpus(tmp_path, FakeAPI())
    publish(database, tmp_path)
    bundle = copy.deepcopy(original)
    bundle["pages"] = [
        {key: c[key] for key in ("url", "title", "text", "categories", "warnings", "fetched_at")}
        for c in bundle["chunks"]
    ]
    bundle["pages"][0]["text"] += "\nImportant prerequisites at the end of the document."
    bundle["config"].update(parent_documents=True, pages_hash=digest(bundle["pages"]))
    bundle["snapshot_id"] = digest(bundle["config"])
    write_json(tmp_path / "corpus.json", bundle)
    staged = publish(database, tmp_path, activate=False)
    assert not staged["active"]
    assert (
        database.execute("SELECT id FROM rag_cloud.snapshots WHERE active").fetchone()["id"]
        == original["snapshot_id"]
    )
    assert (
        database.execute(
            "SELECT count(*) AS n FROM rag_cloud.pages WHERE snapshot_id=%s",
            (staged["snapshot_id"],),
        ).fetchone()["n"]
        == 3
    )
    bundle["pages"][0]["text"] += " tampering"
    write_json(tmp_path / "corpus.json", bundle)
    with pytest.raises(ValueError, match="Parent document checksum"):
        load_bundle(tmp_path)


@pytest.fixture
def database():
    # Reuse the dedicated *_test database guard and rollback fixture.
    from test_database import database as fixture

    yield from fixture.__wrapped__()
