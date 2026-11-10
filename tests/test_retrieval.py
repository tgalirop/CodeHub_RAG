import json

import numpy as np
import pytest

from codehub_rag.embedding import file_hash, prepare_chunks
from codehub_rag.evaluation import relevance_metrics
from codehub_rag.lexical import LexicalIndex, build_artifact, tokens
from codehub_rag.query import expand_query
from codehub_rag.retrieval import reciprocal_rank_fusion


class FakeEmbedder:
    model_key = "test-local-embedding-v1"
    dimensions = 3
    chunk_version = "test-token-budget-v1"
    config = {"backend": "deterministic-test-only"}

    def __init__(self):
        self.document_calls = 0

    def token_count(self, text, **kwargs):
        return len(text.split()) + 2

    def documents(self, texts):
        self.document_calls += len(texts)
        return np.array([self.query(text) for text in texts])

    def query(self, text):
        terms = tokens(text)
        if any(word in terms for word in ("training", "εκπαιδευση")):
            return np.array([1, 0, 0], dtype=np.float32)
        if "java" in terms:
            return np.array([0, 1, 0], dtype=np.float32)
        return np.array([0, 0, 1], dtype=np.float32)


def test_greek_accents_and_technical_terms_preserve_distinctions():
    assert tokens("ΕΚΠΑΙΔΕΥΣΗ εκπαίδευση") == ["εκπαιδευση", "εκπαιδευση"]
    assert tokens("C# C++ .NET Node.js Java JavaScript") == [
        "c#",
        "c++",
        ".net",
        "node.js",
        "java",
        "javascript",
    ]


def test_domain_expansion_retains_greek_query_and_technical_names():
    original = "Εκπαίδευση της ομάδας σε C#"
    expanded, aliases = expand_query(original)
    assert expanded.startswith(original)
    assert "training" in aliases and "team" in aliases
    assert expand_query("C++ JavaScript .NET") == ("C++ JavaScript .NET", [])


def test_retrieval_metrics_count_unique_pages_and_expected_sources():
    result = relevance_metrics(["noise", "good", "good"], ["good", "other-good"])
    assert result == {"hit_at_5": True, "recall_at_5": 0.5, "reciprocal_rank_at_5": 0.5}


def test_rrf_combines_ranks_without_comparing_raw_scores():
    dense = [("semantic", 0.91), ("shared", 0.85)]
    lexical = [("lexical", 20.0), ("shared", 10.0)]
    fused = reciprocal_rank_fusion([dense, lexical])
    assert fused[0][0] == "shared"
    assert fused == reciprocal_rank_fusion([[(key, score * 1000) for key, score in dense], lexical])


def test_token_budget_splitting_preserves_all_source_words(tmp_path):
    words = [f"word{i}" for i in range(900)]
    source = {
        "id": "source",
        "document_version_id": "document",
        "page_id": "page",
        "title": "Training",
        "heading_path": ["Overview"],
        "text": " ".join(words),
        "retrieval_text": "Training " + " ".join(words),
        "word_count": 900,
        "chunker_version": "source",
        "ordinal": 0,
        "url": "https://codehub.gr/test/",
    }
    (tmp_path / "chunks.jsonl").write_text(json.dumps(source) + "\n", encoding="utf-8")
    prepared = prepare_chunks(tmp_path, FakeEmbedder())
    assert len(prepared) > 1
    assert all(item["embedding_tokens"] <= 512 for item in prepared)
    assert set(words) == {word for item in prepared for word in item["text"].split()}
    assert prepared == prepare_chunks(tmp_path, FakeEmbedder())


def artifact(tmp_path):
    chunks = [
        {"id": "csharp", "retrieval_text": "C# .NET training"},
        {"id": "cpp", "retrieval_text": "C++ software engineering"},
        {"id": "java", "retrieval_text": "Java Spring programming"},
    ]
    directory, manifest = build_artifact(tmp_path, "snapshot", chunks, {"example": True})
    return directory, manifest


def test_saved_bm25_reloads_without_building_and_filters_candidates(tmp_path, monkeypatch):
    directory, _ = artifact(tmp_path)
    stats = json.loads((directory / "statistics.json").read_text(encoding="utf-8"))
    assert stats["document_count"] == 3
    assert stats["document_frequencies"]["c#"] == 1
    assert len(stats["document_lengths"]) == 3
    import bm25s

    def forbidden(*args, **kwargs):
        raise AssertionError("Query-time indexing is forbidden")

    monkeypatch.setattr(bm25s.BM25, "index", forbidden)
    index = LexicalIndex(directory, file_hash(directory / "manifest.json"))
    assert index.search("C#", 3)[0][0] == "csharp"
    assert index.search("neverseenword", 3) == []
    assert index.search("training", 3, np.array([0, 1, 1], dtype=np.float32)) == []


def test_corrupted_artifact_is_rejected(tmp_path):
    directory, _ = artifact(tmp_path)
    checksum = file_hash(directory / "manifest.json")
    (directory / "statistics.json").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        LexicalIndex(directory, checksum)
