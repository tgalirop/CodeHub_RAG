"""Seed only a dedicated *_test database for the Node/PostgreSQL integration tests."""

import os
import tempfile
from pathlib import Path

from test_cloud import FakeAPI, make_bundle

from codehub_rag.cloud import embed_corpus, publish
from codehub_rag.database import connect

if os.environ.get("CODEHUB_TEST_DB") != "1":
    raise SystemExit("Requires CODEHUB_TEST_DB=1")
with connect(register=False) as connection:
    name = connection.execute("SELECT current_database() AS name").fetchone()["name"]
    if not name.endswith("_test"):
        raise SystemExit("Requires a dedicated database name ending in _test")
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        make_bundle(directory)
        embed_corpus(directory, FakeAPI())
        publish(connection, directory)
    connection.execute("DELETE FROM rag_cloud.usage")
print("Seeded cloud retrieval fixture in dedicated test database")
