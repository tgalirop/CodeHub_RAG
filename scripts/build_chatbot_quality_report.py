"""Build the reviewed development audit from ignored real API run artifacts."""

# Long report prose and HTML templates are kept intact for editorial review.
# ruff: noqa: E501

import html
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def summarize(rows):
    return {
        "total": len(rows),
        "completed": sum(r["completed"] for r in rows),
        "good": sum(r["assessment"] == "good" for r in rows),
        "partial": sum(r["assessment"] == "partial" for r in rows),
        "fail": sum(r["assessment"] == "fail" for r in rows),
        "median_latency_ms": statistics.median(r["latency_ms"] for r in rows),
        "input_tokens": sum((r["usage"] or {}).get("input_tokens", 0) for r in rows),
        "output_tokens": sum((r["usage"] or {}).get("output_tokens", 0) for r in rows),
    }


NOTES = {
    3: "Correctly distinguishes office and training-centre addresses.",
    10: "46 is scoped to the saved Training Programs catalogue, not current live availability.",
    12: "Finds the named RAG course from a practical paraphrase and gives relevant alternatives.",
    14: "Separates mandatory Python skills from beneficial API/JSON/ML/Git/cloud knowledge.",
    15: "Compares both courses, including duration, scope and prerequisites.",
    16: "Useful AWS introduction, but initial answer misses the basic-AWS-knowledge wording. Targeted final retest explains both source statements.",
    20: "Does not invent price/start date; gives phone/email with correctly mapped citations.",
    21: "61 refers to the saved November 10 catalogue; current active job availability is not verified.",
    23: "Three supported Python/Athens examples, with seniority and additional requirements. Not exhaustive.",
    24: "Preserves Remote/Hybrid discrepancy and the outside-Athens condition for full remote work.",
    25: "Distinguishes React/Electron desktop UI from browser applications; notes source work-mode conflict.",
    27: "Correct Oracle PL/SQL requirements and 2000–2200 EUR gross/month.",
    28: "All quoted salaries belong to the correct entities, but the initial answer places a 3000–3500 overlap first. Final retest separates strict matches. Retrieval is still not an exhaustive salary filter.",
    29: "Resolves the prior Python-job question and retains all three cited jobs.",
    30: "Returns positions 11–20 with no URL overlap with positions 1–10.",
    32: "Correct address distinction; adds an unnecessary example course.",
    37: "Rejects false 3000 EUR premise; correctly gives Payment Engineer 1700–2025 gross/month.",
    38: "Explicitly reports conflicting Remote and Hybrid labels in the source.",
    39: "Correct free participation and December 7, 2026 application deadline in the saved source.",
    40: "Declines unrelated trivia; no irrelevant factual answer or source cards.",
    41: "No secret/action disclosure, but initial answer adds an unrelated .NET role. Final retest declines without arbitrary recommendations.",
    42: "Does not invent a filtered AWS total or substitute 46; exact filtered counting is still unsupported.",
}


def reviewed(path, partial):
    run = read(path)
    rows = []
    for r in sorted(run["rows"], key=lambda item: item["id"]):
        rows.append(
            {
                key: r[key]
                for key in ("id", "question", "answer", "completed", "latency_ms", "transport")
            }
            | {
                "assessment": "partial" if r["id"] in partial else "good",
                "review": NOTES.get(
                    r["id"], "Useful answer supported by the selected website evidence."
                ),
                "usage": r.get("done", {}).get("usage"),
                "sources": [{key: s[key] for key in ("id", "url", "title")} for s in r["sources"]],
            }
        )
    return {"started_at": run["started_at"], "summary": summarize(rows), "rows": rows}


def main():
    baseline = read("reports/site-chatbot-30-review.json")
    report = {
        "date": "2026-11-12",
        "model": "gpt-6-luna",
        "snapshot_id": "4f5abda35d3defa6dbe26d6a8d4a85990cf5bb52b85fbb902412fbd2c81a28f0",
        "corpus": {
            "documents": 167,
            "chunks_before": 2481,
            "chunks_after": 1294,
            "learn_more_chunks_before": 266,
            "learn_more_chunks_after": 0,
            "fetched_on": "2026-11-10",
        },
        "methodology": [
            "Assistant qualitative review against saved source pages, not an independent judge or general accuracy estimate.",
            "Baseline: 18 public Vercel answers and 12 unchanged local production-handler answers after public rate limiting.",
            "Improved runs: actual production handler locally with real Neon/OpenAI and staged snapshot; batch-local request reservation, unchanged public quotas.",
            "30 repeated development cases and 12 additional cases. After inspecting failures, generic prompt rules were refined and 3 targeted cases retested. Do not merge retests into a claimed independent 100% success rate.",
            "One answer per case per run; no statistical estimate of generation variability. No browser visual QA. UI behavior is covered by DOM regression tests.",
            "Saved November 10 HTML was re-extracted, not freshly crawled. Listings and totals do not prove current availability. Exact constrained counts and exhaustive filtered lists remain limitations.",
            "Token usage includes planning/evidence/generation, excludes query embeddings. Fuller parent evidence substantially increases input tokens. Initial re-embedding used 163049 input tokens for 1294 chunks. No price estimate is asserted.",
            "Final numeric/prerequisite/injection rules were tested on 3 targeted cases; the entire 42-case suite was not repeated after those last prompt changes.",
        ],
        "baseline": baseline["summary"],
        "repeated_30": reviewed("data/cloud-v2/answers-final.json", {16, 28}),
        "additional_12": reviewed("data/cloud-v2/answers-holdout.json", {41, 42}),
        "final_targeted_retests": reviewed("data/cloud-v2/answers-retest-final.json", set()),
        "checks": [
            "Python default: 44 passed, 8 database skips",
            "Dedicated PostgreSQL Python suite: 11 passed",
            "Node default: 35 passed, 1 database skip",
            "Real Node/PostgreSQL integration: 1 passed",
            "Ruff, formatting, shared prompt/config export and static build passed",
        ],
    }
    for r in report["final_targeted_retests"]["rows"]:
        r["review"] = {
            16: "Explains basic knowledge versus recommended experience, and labels the alternative Discovery Day as completed.",
            28: "Project Manager 3800–4000 and IT Business Analyst 3500–4000 are correctly sourced strict matches; overlapping ranges explicitly excluded. Not exhaustive.",
            41: "Declines the injection-only request with no unrelated sources or claimed actions.",
        }[r["id"]]
    output = ROOT / "reports/chatbot-quality-2026-11-12"
    output.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    escape = html.escape
    body = "<h1>Code.Hub chatbot · Έλεγχος βελτίωσης</h1><p>12 Νοεμβρίου 2026 · gpt-6-luna · πραγματικές κλήσεις API</p>"
    body += "<p><strong>Ίδιες 30 ερωτήσεις:</strong> πριν 14 καλές / 6 μερικές / 10 ανεπαρκείς· μετά 28 καλές / 2 μερικές / 0 ανεπαρκείς. Τρεις μεταγενέστεροι στοχευμένοι έλεγχοι παρουσιάζονται χωριστά.</p>"
    body += (
        "<h2>Μέθοδος και όρια</h2><ul>"
        + "".join(f"<li>{escape(x)}</li>" for x in report["methodology"])
        + "</ul>"
    )
    for key, title in [
        ("repeated_30", "Επανάληψη 30 ερωτήσεων"),
        ("additional_12", "12 επιπλέον ερωτήσεις"),
        ("final_targeted_retests", "Τελικοί στοχευμένοι επανέλεγχοι"),
    ]:
        group = report[key]
        body += f"<h2>{title}</h2><pre>{escape(json.dumps(group['summary'], indent=2))}</pre>"
        for r in group["rows"]:
            body += f'<details><summary>{r["id"]}. {escape(r["question"])} <b class="{r["assessment"]}">{r["assessment"]}</b></summary><p>{escape(r["review"])}</p><pre>{escape(r["answer"])}</pre><ul>'
            body += "".join(
                f'<li><a href="{escape(s["url"], quote=True)}">{escape(s["title"])}</a></li>'
                for s in r["sources"]
            )
            body += "</ul></details>"
    body += (
        "<h2>Έλεγχοι κώδικα</h2><ul>"
        + "".join(f"<li>{escape(x)}</li>" for x in report["checks"])
        + "</ul>"
    )
    page = (
        '<!doctype html><html lang="el"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Code.Hub chatbot quality review</title><style>body{font:16px/1.65 system-ui;max-width:1000px;margin:40px auto;padding:0 24px;color:#211335;background:#fcfaf9}h1,h2{line-height:1.2}details{border:1px solid #ddd4e4;border-radius:10px;padding:16px;margin:12px 0}summary{cursor:pointer;font-weight:600}pre{white-space:pre-wrap;font:inherit;background:#f2edf5;padding:16px;border-radius:8px}.good{color:#28654b}.partial{color:#a14b14}a{color:#6a377e}</style>'
        + body
        + "</html>"
    )
    output.with_suffix(".html").write_text(page, encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]["summary"]
                for k in ("repeated_30", "additional_12", "final_targeted_retests")
            }
        )
    )


if __name__ == "__main__":
    main()
