"""Seed only a dedicated *_test database for the Node/PostgreSQL integration tests."""

import os
import tempfile
from pathlib import Path

from test_cloud import FakeAPI, make_bundle

from codehub_rag.cloud import digest, embed_corpus, publish
from codehub_rag.database import connect
from codehub_rag.ingest import write_json

if os.environ.get("CODEHUB_TEST_DB") != "1":
    raise SystemExit("Requires CODEHUB_TEST_DB=1")
with connect(register=False) as connection:
    name = connection.execute("SELECT current_database() AS name").fetchone()["name"]
    if not name.endswith("_test"):
        raise SystemExit("Requires a dedicated database name ending in _test")
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        bundle = make_bundle(directory)
        bundle["pages"] = [
            {
                key: c[key]
                for key in ("url", "title", "text", "categories", "warnings", "fetched_at")
            }
            for c in bundle["chunks"]
        ]
        for page in bundle["pages"]:
            page["text"] += "\nExpanded parent document with complete prerequisites."
        bundle["config"].update(parent_documents=True, pages_hash=digest(bundle["pages"]))
        bundle["snapshot_id"] = digest(bundle["config"])
        write_json(directory / "corpus.json", bundle)
        embed_corpus(directory, FakeAPI())
        publish(connection, directory)
    connection.execute("DELETE FROM rag_cloud.usage")
print("Seeded cloud retrieval fixture in dedicated test database")
