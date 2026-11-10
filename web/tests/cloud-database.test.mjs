import test from "node:test";
import assert from "node:assert/strict";
import { database, createStore } from "../lib/store.js";
import { expandQuery } from "../lib/lexical.js";

const enabled =
  process.env.CODEHUB_TEST_DB === "1" && process.env.CLOUD_DATABASE_URL;
test(
  "real PostgreSQL cloud retrieval, filtering and durable request reservation",
  { skip: !enabled },
  async () => {
    const name = new URL(process.env.CLOUD_DATABASE_URL).pathname;
    assert.match(name, /_test$/);
    const sql = database();
    try {
      const store = createStore(sql);
      const snapshot = await store.snapshot();
      assert.equal(snapshot.documents, 3);
      assert.equal(snapshot.chunks, 3);
      const vector = [1, ...Array(383).fill(0)];
      const sources = await store.search(
        snapshot,
        expandQuery("εκπαίδευση C#"),
        vector,
      );
      assert.equal(sources.length, 3);
      assert.match(sources[0].url, /^https:\/\/codehub.gr\//);
      assert.equal(typeof sources[0].text, "string");
      assert.deepEqual(
        sources.map((s) => s.id),
        [1, 2, 3],
      );
      const filtered = await store.search(
        snapshot,
        "training",
        vector,
        "course",
      );
      assert.equal(filtered.length, 1);
      assert.ok(filtered.every((s) => s.categories.includes("course")));
      const absent = await store.search(snapshot, "training", vector, "post");
      assert.equal(absent.length, 0);
      assert.equal(await store.catalogueCount(snapshot), null);
      const jobs = await store.listJobs(snapshot, 0);
      assert.equal(jobs.total, 2);
      assert.equal(jobs.sources.length, 2);
      assert.ok(jobs.sources.every((row) => row.categories.includes("job")));
      assert.equal(jobs.next, null);
      assert.equal((await store.snapshot(snapshot.id)).id, snapshot.id);
      const decisions = await Promise.all(
        Array.from({ length: 5 }, () =>
          store.reserve("integration-test", 100, 2),
        ),
      );
      assert.equal(decisions.filter(Boolean).length, 2);
    } finally {
      await sql.end();
    }
  },
);
