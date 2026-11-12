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
      assert.equal(snapshot.documents, 4);
      assert.equal(snapshot.chunks, 4);
      const vector = [1, ...Array(383).fill(0)];
      const sources = await store.search(
        snapshot,
        expandQuery("εκπαίδευση C#"),
        vector,
      );
      assert.equal(sources.length, 4);
      assert.match(sources[0].url, /^https:\/\/codehub.gr\//);
      assert.equal(typeof sources[0].text, "string");
      assert.match(
        sources[0].text,
        /Expanded parent document with complete prerequisites/,
      );
      assert.deepEqual(
        sources.map((s) => s.id),
        [1, 2, 3, 4],
      );
      const details = await store.search(snapshot, "salary", vector, null, {
        preferredKind: "job",
      });
      assert.equal(details.length, 3);
      assert.ok(
        details.every((s) => !s.url.endsWith("/open-job-opportunities/")),
      );
      // An inferred preference still permits useful sources of another kind.
      assert.ok(details.some((s) => s.categories.includes("course")));
      const courses = await store.coursePages(snapshot);
      assert.equal(courses.length, 1);
      const bounded = await store.search(snapshot, "training", vector, null, {
        preferredKind: "course",
        allowedUrls: courses.map((c) => c.url),
      });
      assert.deepEqual(
        bounded.map((s) => s.url),
        courses.map((c) => c.url),
      );
      assert.deepEqual(
        await store.search(snapshot, "training", vector, null, {
          allowedUrls: [],
        }),
        [],
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
      const jobs = await store.listCatalogue(snapshot, "job", 0);
      assert.equal(jobs.total, 2);
      assert.equal(jobs.sources.length, 2);
      assert.ok(jobs.sources.every((row) => row.categories.includes("job")));
      assert.equal(jobs.next, null);
      assert.equal((await store.listCatalogue(snapshot, "course", 0)).total, 1);
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
