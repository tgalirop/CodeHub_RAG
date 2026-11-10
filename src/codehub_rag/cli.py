from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from .ingest import crawl, inventory, reprocess
from .report import build_report
from .web import FetchError, SiteClient


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Must be a positive integer")
    return number


def nonnegative(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("Must be >= 0")
    return number


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Code.Hub site audit and ingestion prototype")
    commands = parser.add_subparsers(dest="command", required=True)
    serve_parser = commands.add_parser("serve", help="Start the local chatbot and FastAPI service")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=positive, default=8000)
    audit = commands.add_parser("audit", help="Discover sitemap URLs and extract a sample")
    audit.add_argument("--output", type=Path, default=Path("data/runs"))
    audit.add_argument(
        "--sample", type=nonnegative, default=15, help="Sample size; 0 = inventory only"
    )
    crawl_parser = commands.add_parser("crawl", help="Extract pages from an existing inventory")
    crawl_parser.add_argument("run", type=Path)
    size = crawl_parser.add_mutually_exclusive_group()
    size.add_argument("--limit", type=positive, default=15)
    size.add_argument(
        "--all", action="store_true", help="Crawl all inventory URLs (hard cap 10,000)"
    )
    crawl_parser.add_argument(
        "--discover", action="store_true", help="Also follow in-scope page links"
    )
    crawl_parser.add_argument(
        "--overwrite", action="store_true", help="Replace previous extraction outputs"
    )
    offline = commands.add_parser(
        "reprocess", help="Replace extraction from saved HTML; no network"
    )
    offline.add_argument("run", type=Path)
    report_parser = commands.add_parser("report", help="Write a shareable audit summary")
    report_parser.add_argument("run", type=Path)
    report_parser.add_argument("--output", type=Path, required=True)
    commands.add_parser("migrate", help="Apply transactional database migrations")
    load_parser = commands.add_parser(
        "load", help="Idempotently import documents and source chunks"
    )
    load_parser.add_argument("run", type=Path)
    model_parser = commands.add_parser("model-download", help="Download pinned local E5 ONNX files")
    index_parser = commands.add_parser(
        "index", help="Build vectors/BM25 and atomically activate a snapshot"
    )
    index_parser.add_argument("run", type=Path)
    index_parser.add_argument("--artifacts", type=Path, default=Path("data/indexes"))
    search_parser = commands.add_parser("search", help="Search the active immutable snapshot")
    search_parser.add_argument("query", nargs="?")
    search_parser.add_argument(
        "--interactive", action="store_true", help="Reuse the model and BM25 between queries"
    )
    search_parser.add_argument("--mode", choices=["hybrid", "dense", "bm25"], default="hybrid")
    search_parser.add_argument("--kind", choices=["page", "post", "course", "training", "job"])
    search_parser.add_argument("--limit", type=positive, default=5)
    search_parser.add_argument("--candidates", type=positive, default=40)
    evaluate_parser = commands.add_parser(
        "evaluate", help="Compare retrieval on labeled smoke questions"
    )
    evaluate_parser.add_argument(
        "--questions", type=Path, default=Path("evaluation/questions.jsonl")
    )
    evaluate_parser.add_argument(
        "--output", type=Path, default=Path("data/retrieval-evaluation.json")
    )
    for command in (model_parser, index_parser, search_parser, evaluate_parser):
        command.add_argument("--models", type=Path, default=Path("data/models"))
    for command in (index_parser, search_parser, evaluate_parser):
        command.add_argument("--threads", type=positive, default=4)
    for command in (audit, crawl_parser):
        command.add_argument(
            "--delay", type=float, default=0.8, help="Minimum seconds between requests"
        )
    args = parser.parse_args()
    if getattr(args, "delay", 0) < 0:
        parser.error("--delay must be >= 0")
    try:
        if args.command == "serve":
            import uvicorn

            if args.port > 65535:
                parser.error("Port must be <= 65535")
            uvicorn.run("codehub_rag.api:app", host=args.host, port=args.port)
            return 0
        if args.command in {"migrate", "load", "model-download", "index", "search", "evaluate"}:
            return retrieval_command(args, parser)
        if args.command == "report":
            content = build_report(args.run)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(content, encoding="utf-8")
            print(f"Report written: {args.output}")
            return 0
        if args.command == "reprocess":
            report = reprocess(args.run)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        with SiteClient(delay=args.delay) as client:
            if args.command == "audit":
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
                directory = args.output / stamp
                print(f"Run directory: {directory}", flush=True)
                audit_report = inventory(client, directory)
                report = {"run_directory": str(directory), "audit": audit_report}
                if args.sample and audit_report["urls"]:
                    report["crawl"] = crawl(client, directory, limit=args.sample, discover=False)
                failed = not audit_report["inventory_complete"] or bool(
                    report.get("crawl", {}).get("errors")
                )
            else:
                directory = args.run
                if (directory / "documents.jsonl").exists() and not args.overwrite:
                    parser.error(
                        "Extraction already exists; use --overwrite or create a new audit run"
                    )
                report = crawl(
                    client,
                    directory,
                    limit=None if args.all else args.limit,
                    discover=args.discover,
                )
                failed = bool(report["errors"])
                report = {
                    "run_directory": str(directory),
                    "audit": json.loads((directory / "audit.json").read_text(encoding="utf-8")),
                    "crawl": report,
                }
            (directory / "summary.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2 if failed else 0
    except psycopg.Error as error:
        parser.exit(
            1,
            f"Database operation failed ({error.sqlstate or type(error).__name__}). "
            "Check database connectivity and run migrate first.\n",
        )
    except (FetchError, OSError, ValueError) as error:
        parser.exit(1, f"Ingestion failed: {error}\n")


def retrieval_command(args, parser) -> int:
    from .database import connect, import_run, migrate
    from .embedding import MODEL_REVISION, Embedder, prepare_model
    from .retrieval import SearchEngine, build_index

    if args.command == "model-download":
        print(prepare_model(args.models))
        return 0
    if args.command == "migrate":
        with connect(register=False) as connection:
            print(json.dumps({"applied": migrate(connection)}))
        return 0
    if args.command == "load":
        with connect() as connection:
            print(json.dumps(import_run(connection, args.run)))
        return 0
    embedder = Embedder(
        args.models / f"multilingual-e5-small-{MODEL_REVISION}", threads=args.threads
    )
    with connect() as connection:
        if args.command == "evaluate":
            from .evaluation import evaluate

            print(json.dumps(evaluate(connection, embedder, args.questions, args.output), indent=2))
            return 0
        if args.command == "index":
            print(json.dumps(build_index(connection, args.run, embedder, args.artifacts), indent=2))
            return 0
        engine = SearchEngine(connection, embedder)

        def show(query):
            results = engine.search(
                query, mode=args.mode, limit=args.limit, candidates=args.candidates, kind=args.kind
            )
            print(
                json.dumps(
                    {"query": query, "mode": args.mode, "results": results},
                    ensure_ascii=False,
                    indent=2,
                )
            )

        if args.query:
            show(args.query)
        if args.interactive:
            while True:
                try:
                    question = input("Search (blank to quit)> ").strip()
                except EOFError:
                    break
                if not question:
                    break
                try:
                    show(question)
                except ValueError as error:
                    print(f"Query rejected: {error}")
        elif not args.query:
            parser.error("Provide a query or use --interactive")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
