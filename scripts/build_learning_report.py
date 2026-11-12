"""Build a shareable review from saved evaluation results, without raw API events."""

import argparse
import html
import json
from pathlib import Path
from statistics import median


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("data/cloud-learning"))
    parser.add_argument("--output", type=Path, default=Path("reports/learning-advisor-2026-11-12"))
    args = parser.parse_args()
    batches = []
    for name in ["advisor", "regression-30", "public"]:
        path = args.directory / f"answers-{name}.json"
        if not path.exists():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = []
        for row in sorted(raw["rows"], key=lambda r: r["id"]):
            rows.append(
                {
                    key: row.get(key)
                    for key in [
                        "id",
                        "question",
                        "check",
                        "advisor",
                        "answer",
                        "completed",
                        "transport",
                        "http_status",
                        "latency_ms",
                    ]
                }
                | {
                    "sources": [
                        {key: s.get(key) for key in ["title", "url", "fetched_at"]}
                        for s in row.get("sources", [])
                    ]
                }
            )
        batches.append(
            {
                "name": name,
                "started_at": raw["started_at"],
                "status": raw.get("local_status", raw.get("status")),
                "completed": sum(bool(r["completed"]) for r in rows),
                "total": len(rows),
                "median_latency_ms": median(r["latency_ms"] for r in rows),
                "rows": rows,
            }
        )
    report = {
        "title": "Code.Hub — Learning advisor release review",
        "date": "2026-11-12",
        "snapshot_id": "951064a6a1ec6da00ec3beba168907a9cefde77522621a0c6f0ad9851ac95e48",
        "source_collection_date": "2026-11-10",
        "corpus": {"documents": 167, "chunks": 1754, "courses": 46},
        "review": [
            "Six advisor cases were manually reviewed against retrieved source facts.",
            "All six satisfied their stated checks in this development run.",
            "The 30-question regression completed; completion is not an accuracy score.",
            "Case 14 now correctly separates required Python from optional skills.",
            "Case 15 covers both selected courses, including their 24/88-hour durations.",
        ],
        "limitations": [
            "Regression case 29 missed evidence for one location in a follow-up question. "
            "Ambiguous job titles and incomplete retrieval can still reduce recall.",
            "Source HTML was collected on November 10 and reprocessed, not freshly crawled.",
            "45 of 46 courses have positive published durations. A zero-hour value is unknown.",
            "The browser tool stopped because it could not verify the active Chrome URL. "
            "DOM interactions were tested; desktop/mobile appearance was not visually verified.",
            "These development examples are not a held-out benchmark or accuracy guarantee. "
            "Model responses and latency can vary.",
        ],
        "batches": batches,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    esc = html.escape
    parts = [
        '<!doctype html><html lang="en"><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>{esc(report['title'])}</title>",
        "<style>body{font:16px/1.65 system-ui;background:#faf8f7;color:#201335;"
        "max-width:1000px;margin:40px auto;padding:0 20px}h1{line-height:1.2}"
        "h2{margin-top:40px}details{background:white;border:1px solid #ddd3e5;"
        "border-radius:12px;margin:12px 0;padding:16px}summary{cursor:pointer;"
        "font-weight:600}.answer{white-space:pre-wrap}a{color:#653b8e}"
        ".note{border-left:4px solid #fc624f;padding-left:18px}small{color:#655a70}"
        "code{overflow-wrap:anywhere}</style>",
        f"<h1>{esc(report['title'])}</h1><p>12 November 2026 · "
        '<a href="https://codehub-rag.vercel.app/">Live demo</a></p>',
        "<p>Guided goals, declared skills, per-course duration limits, exact course "
        "comparisons and a visible evidence trail.</p>",
        f"<p>Source snapshot: <code>{report['snapshot_id']}</code></p>",
        "<h2>Review</h2><ul>",
        *[f"<li>{esc(item)}</li>" for item in report["review"]],
        '</ul><div class="note"><h2>Limits and remaining work</h2><ul>',
        *[f"<li>{esc(item)}</li>" for item in report["limitations"]],
        "</ul></div>",
    ]
    for batch in batches:
        parts.append(
            f"<h2>{esc(batch['name'])}</h2><p>{batch['completed']}/{batch['total']} "
            f"completed · median {batch['median_latency_ms'] / 1000:.1f}s</p>"
        )
        for row in batch["rows"]:
            parts.append(
                f"<details><summary>{row['id']}. {esc(row['question'])}</summary>"
                f"<p><small>{esc(row['transport'])} · {row['latency_ms']} ms</small></p>"
                f"<p><b>Check:</b> {esc(row['check'] or '')}</p>"
            )
            if row["advisor"]:
                parts.append(
                    f"<p>Profile: {esc(json.dumps(row['advisor'], ensure_ascii=False))}</p>"
                )
            parts.append(f'<div class="answer">{esc(row["answer"])}</div><ul>')
            for source in row["sources"]:
                parts.append(
                    f'<li><a href="{esc(source["url"], quote=True)}">'
                    f"{esc(source['title'])}</a></li>"
                )
            parts.append("</ul></details>")
    parts.append("</html>")
    args.output.with_suffix(".html").write_text("\n".join(parts), encoding="utf-8")
    print(json.dumps({"batches": len(batches), "report": str(args.output)}))


if __name__ == "__main__":
    main()
