from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

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
    parser = argparse.ArgumentParser(description="Code.Hub site audit and ingestion prototype")
    commands = parser.add_subparsers(dest="command", required=True)
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
    for command in (audit, crawl_parser):
        command.add_argument(
            "--delay", type=float, default=0.8, help="Minimum seconds between requests"
        )
    args = parser.parse_args()
    if getattr(args, "delay", 0) < 0:
        parser.error("--delay must be >= 0")
    try:
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
    except (FetchError, OSError, ValueError) as error:
        parser.exit(1, f"Ingestion failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
