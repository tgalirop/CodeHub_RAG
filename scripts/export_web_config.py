"""Generate shared tokenizer/glossary/prompt assets; --check detects drift in CI."""

import argparse
import json
from pathlib import Path

from codehub_rag.chat import GATE_INSTRUCTIONS, INSTRUCTIONS
from codehub_rag.cloud import lexical_config

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1] / "web/lib"
for name, value in {
    "search-config.json": lexical_config(),
    "chat-config.json": {"instructions": INSTRUCTIONS, "gate_instructions": GATE_INSTRUCTIONS},
}.items():
    content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path = root / name
    if args.check:
        if not path.exists() or json.loads(path.read_text(encoding="utf-8")) != value:
            raise SystemExit(f"Run uv run python scripts/export_web_config.py: {name} differs")
    else:
        path.write_text(content, encoding="utf-8")
print(
    "Shared web configuration matches Python" if args.check else "Shared web configuration written"
)
