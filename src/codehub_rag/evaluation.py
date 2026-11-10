"""Small labeled retrieval smoke set; not a held-out production benchmark."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from .embedding import file_hash
from .ingest import read_jsonl, write_json
from .query import QUERY_VERSION, expand_query
from .retrieval import SearchEngine


def relevance_metrics(urls: list[str], expected: list[str]) -> dict:
    if not expected:
        raise ValueError("Positive retrieval cases require at least one expected URL")
    unique = list(dict.fromkeys(urls))[:5]
    gold = set(expected)
    hits = set(unique) & gold
    first = next((rank for rank, url in enumerate(unique, 1) if url in gold), None)
    return {
        "hit_at_5": bool(hits),
        "recall_at_5": len(hits) / len(gold),
        "reciprocal_rank_at_5": 1 / first if first else 0,
    }


def evaluate(connection, embedder, questions: Path, output: Path) -> dict:
    cases = read_jsonl(questions)
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Evaluation requires non-empty, uniquely identified cases")
    engine = SearchEngine(connection, embedder)
    available = {row["url"] for row in engine.metadata.values()}
    for case in cases:
        if not set(case["expected_urls"]) <= available:
            raise ValueError(f"Evaluation case references absent source URLs: {case['id']}")
    embedder.query(cases[0]["query"])
    rows = []
    for case in cases:
        for mode in ("bm25", "dense", "hybrid"):
            start = time.perf_counter()
            results = engine.search(
                case["query"], mode=mode, kind=case.get("kind"), limit=5, candidates=40, per_page=1
            )
            elapsed = (time.perf_counter() - start) * 1000
            urls = [item["url"] for item in results]
            rows.append(
                {
                    "case_id": case["id"],
                    "language": case["language"],
                    "query": case["query"],
                    "expanded_query": expand_query(case["query"])[0],
                    "mode": mode,
                    "kind": case.get("kind"),
                    "expected_urls": case["expected_urls"],
                    "ranked_urls": urls,
                    "elapsed_ms": elapsed,
                    **relevance_metrics(urls, case["expected_urls"]),
                }
            )
    summary = {}
    for mode in ("bm25", "dense", "hybrid"):
        selected = [row for row in rows if row["mode"] == mode]
        summary[mode] = {
            "queries": len(selected),
            "hit_rate_at_5": sum(row["hit_at_5"] for row in selected) / len(selected),
            "mean_recall_at_5": float(np.mean([row["recall_at_5"] for row in selected])),
            "mrr_at_5": float(np.mean([row["reciprocal_rank_at_5"] for row in selected])),
            "warm_latency_p50_ms": float(np.median([row["elapsed_ms"] for row in selected])),
        }
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "snapshot_id": engine.snapshot_id,
        "questions_sha256": file_hash(questions),
        "question_count": len(cases),
        "scope": "Curated positive smoke set; not held out; no answer or abstention evaluation",
        "settings": {
            "unique_pages": 5,
            "candidates_per_retriever": 40,
            "rrf_constant": 60,
            "fusion_unit": "canonical page",
            "query_expansion": QUERY_VERSION,
            "latency": "Warm queries, excludes model and index loading; local CPU/PostgreSQL",
        },
        "summary": summary,
        "results": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, report)
    return {"output": str(output), "snapshot_id": engine.snapshot_id, "summary": summary}
