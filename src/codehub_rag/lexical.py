"""Persistent BM25S scores, explicit corpus statistics and technical-term tokenization."""

from __future__ import annotations

import json
import math
import re
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path

import bm25s
import numpy as np

from .embedding import file_hash
from .ingest import write_json

TOKENIZER_VERSION = "el-en-tech-v2"
PARAMETERS = {"k1": 1.5, "b": 0.75, "method": "lucene", "backend": "numpy"}
STOPWORDS = set(
    """a an the and or of to for in on at by with from is are be it this that
    we our you your as ο η το οι τα του τη την τον της των τους στον στην στο στα στις
    σε με για και η απο ενα μια ενας ειναι να θα σας μας μου σου που πως μπορω θελω
    εχω μπορειτε αυτη αυτο αυτα αυτες αυτος τις ως αν αλλα""".split()
)
PATTERN = re.compile(r"(?u)(?:\.[^\W\d_]\w*|[^\W_]+(?:[.+#][^\W_]+|[+#]+)*)")


def tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return [term for term in PATTERN.findall(normalized) if term not in STOPWORDS]


def verify_artifact(directory: Path, expected_checksum: str | None = None) -> dict:
    manifest_path = directory / "manifest.json"
    if expected_checksum and file_hash(manifest_path) != expected_checksum:
        raise ValueError("BM25 manifest checksum mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["tokenizer_version"] != TOKENIZER_VERSION:
        raise ValueError("BM25 tokenizer version mismatch")
    for name, checksum in manifest["files"].items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()) or file_hash(path) != checksum:
            raise ValueError(f"BM25 artifact checksum mismatch: {name}")
    return manifest


def build_artifact(
    root: Path, snapshot_id: str, chunks: list[dict], config: dict
) -> tuple[Path, dict]:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / snapshot_id
    if target.exists():
        manifest = verify_artifact(target)
        if manifest["config"] != config or manifest["chunk_ids"] != [c["id"] for c in chunks]:
            raise ValueError("Existing snapshot artifact has a different corpus/configuration")
        return target, manifest
    corpus_tokens = [tokens(item["retrieval_text"]) for item in chunks]
    if not corpus_tokens or any(not row for row in corpus_tokens):
        raise ValueError("BM25 requires non-empty tokenized chunks")
    frequencies = Counter(term for row in corpus_tokens for term in set(row))
    n_documents = len(corpus_tokens)
    lengths = [len(row) for row in corpus_tokens]
    statistics = {
        "document_count": n_documents,
        "average_document_length": sum(lengths) / n_documents,
        "document_lengths": lengths,
        "vocabulary_size": len(frequencies),
        "document_frequencies": dict(sorted(frequencies.items())),
        "idf": {
            term: math.log(1 + (n_documents - count + 0.5) / (count + 0.5))
            for term, count in sorted(frequencies.items())
        },
        "parameters": PARAMETERS,
        "tokenizer_version": TOKENIZER_VERSION,
    }
    retriever = bm25s.BM25(**PARAMETERS)
    retriever.index(corpus_tokens, show_progress=False)
    with tempfile.TemporaryDirectory(prefix=".building-", dir=root) as temporary:
        directory = Path(temporary)
        if not directory.resolve().is_relative_to(root):
            raise ValueError("Temporary build directory escaped the intended artifact root")
        retriever.save(str(directory / "bm25"))
        write_json(directory / "statistics.json", statistics)
        manifest = {
            "snapshot_id": snapshot_id,
            "config": config,
            "tokenizer_version": TOKENIZER_VERSION,
            "chunk_ids": [item["id"] for item in chunks],
            "files": {
                path.relative_to(directory).as_posix(): file_hash(path)
                for path in sorted(directory.rglob("*"))
                if path.is_file()
            },
        }
        write_json(directory / "manifest.json", manifest)
        verify_artifact(directory)
        try:
            directory.rename(target)
        except FileExistsError:
            other = verify_artifact(target)
            if other != manifest:
                raise ValueError("Concurrent BM25 build produced a different artifact") from None
    return target, manifest


class LexicalIndex:
    def __init__(self, directory: Path, checksum: str):
        self.manifest = verify_artifact(directory, checksum)
        self.chunk_ids = self.manifest["chunk_ids"]
        self.retriever = bm25s.BM25.load(
            str(directory / "bm25"),
            mmap=True,
            load_corpus=False,
            show_progress=False,
        )

    def search(
        self, query: str, limit: int, mask: np.ndarray | None = None
    ) -> list[tuple[str, float]]:
        query_tokens = tokens(query)
        if not query_tokens:
            return []
        ids, scores = self.retriever.retrieve(
            [query_tokens],
            k=min(limit, len(self.chunk_ids)),
            weight_mask=mask,
            show_progress=False,
            backend_selection="numpy",
        )
        return [
            (self.chunk_ids[int(position)], float(score))
            for position, score in zip(ids[0], scores[0], strict=True)
            if score > 0
        ]
