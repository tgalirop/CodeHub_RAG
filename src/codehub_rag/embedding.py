"""Pinned local E5-small ONNX model, explicit prefixes and token-budget preparation."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from .extract import digest
from .ingest import read_jsonl, write_json, write_jsonl

MODEL_NAME = "intfloat/multilingual-e5-small"
MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
MODEL_KEY = f"{MODEL_NAME}@{MODEL_REVISION}:onnx-mean-l2-v1"
DIMENSIONS = 384
MAX_TOKENS = 512
MODEL_FILES = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "onnx/model.onnx",
)
CHUNK_VERSION = f"e5-512-v1:{MODEL_REVISION}"


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare_model(root: Path = Path("data/models")) -> Path:
    from huggingface_hub import snapshot_download

    directory = root / f"multilingual-e5-small-{MODEL_REVISION}"
    snapshot_download(
        MODEL_NAME,
        revision=MODEL_REVISION,
        allow_patterns=list(MODEL_FILES),
        local_dir=directory,
        token=False,
        max_workers=2,
    )
    hashes = {name: file_hash(directory / name) for name in MODEL_FILES}
    write_json(
        directory / "codehub-model.json",
        {
            "model": MODEL_KEY,
            "revision": MODEL_REVISION,
            "dimensions": DIMENSIONS,
            "files": hashes,
            "pooling": "mean",
            "normalization": "l2",
            "query_prefix": "query: ",
            "passage_prefix": "passage: ",
            "max_tokens": MAX_TOKENS,
        },
    )
    return directory


class Embedder:
    model_key = MODEL_KEY
    dimensions = DIMENSIONS
    chunk_version = CHUNK_VERSION

    def __init__(self, directory: Path, threads: int = 4):
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType
        from tokenizers import Tokenizer

        self.config = json.loads((directory / "codehub-model.json").read_text(encoding="utf-8"))
        if self.config["model"] != MODEL_KEY:
            raise ValueError("Embedding model identity mismatch")
        for name in MODEL_FILES:
            if file_hash(directory / name) != self.config["files"][name]:
                raise ValueError(f"Embedding model checksum mismatch: {name}")
        if not any(m["model"] == MODEL_NAME for m in TextEmbedding.list_supported_models()):
            TextEmbedding.add_custom_model(
                model=MODEL_NAME,
                pooling=PoolingType.MEAN,
                normalization=True,
                sources=ModelSource(hf=MODEL_NAME),
                dim=DIMENSIONS,
                model_file="onnx/model.onnx",
            )
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.encoder = TextEmbedding(
            model_name=MODEL_NAME,
            specific_model_path=str(directory.resolve()),
            local_files_only=True,
            threads=threads,
            providers=["CPUExecutionProvider"],
        )

    def token_count(self, text: str, *, query: bool = False) -> int:
        prefix = "query: " if query else "passage: "
        return len(self.tokenizer.encode(prefix + text).ids)

    def documents(self, texts: list[str]) -> np.ndarray:
        if any(self.token_count(text) > MAX_TOKENS for text in texts):
            raise ValueError("Passage exceeds embedding token budget; prepare chunks first")
        values = np.asarray(
            list(
                self.encoder.embed(
                    ["passage: " + text for text in texts],
                    batch_size=16,
                )
            ),
            dtype=np.float32,
        )
        if values.shape != (len(texts), self.dimensions) or not np.isfinite(values).all():
            raise ValueError("Invalid passage embeddings")
        return values

    def query(self, text: str) -> np.ndarray:
        if not text.strip() or self.token_count(text, query=True) > MAX_TOKENS:
            raise ValueError("Query is empty or exceeds the 512-token budget")
        value = np.asarray(next(self.encoder.embed(["query: " + text])), dtype=np.float32)
        if value.shape != (self.dimensions,) or not np.isfinite(value).all():
            raise ValueError("Invalid query embedding")
        return value


def prepare_chunks(run: Path, embedder) -> list[dict]:
    """Re-split long passages without silently truncating source content."""
    source = read_jsonl(run / "chunks.jsonl")
    result = []
    ordinals: dict[str, int] = defaultdict(int)
    for item in source:
        context = " > ".join([item["title"], *item["heading_path"]])
        context_words = context.split()
        while embedder.token_count(" ".join(context_words)) > 110:
            context_words = context_words[:-1]
        context = " ".join(context_words)
        words = item["text"].split()
        start = 0
        while start < len(words):
            low, high = 1, len(words) - start
            best = 0
            while low <= high:
                length = (low + high) // 2
                value = context + "\n" + " ".join(words[start : start + length])
                if embedder.token_count(value) <= MAX_TOKENS:
                    best = length
                    low = length + 1
                else:
                    high = length - 1
            if best == 0:
                raise ValueError("A source word exceeds the embedding budget; review the document")
            body = " ".join(words[start : start + best])
            text = context + "\n" + body
            ordinal = ordinals[item["document_version_id"]]
            ordinals[item["document_version_id"]] += 1
            record = {
                **item,
                "ordinal": ordinal,
                "text": body,
                "retrieval_text": text,
                "chunker_version": embedder.chunk_version,
                "word_count": len(body.split()),
                "source_chunk_id": item["id"],
                "embedding_tokens": embedder.token_count(text),
            }
            record["id"] = digest(
                f"{item['document_version_id']}:{embedder.chunk_version}:{ordinal}:{text}"
            )
            result.append(record)
            if start + best >= len(words):
                break
            start += best - min(30, best // 4)
    return result


def save_prepared(run: Path, chunks: list[dict]) -> Path:
    key = digest("\n".join(sorted(item["id"] for item in chunks)))
    directory = Path("data/prepared") / key
    directory.mkdir(parents=True, exist_ok=True)
    write_jsonl(directory / "chunks.jsonl", chunks)
    write_json(directory / "manifest.json", {"source_run": run.name, "corpus_hash": key})
    return directory
