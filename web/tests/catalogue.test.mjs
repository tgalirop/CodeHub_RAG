import test from "node:test";
import assert from "node:assert/strict";
import { catalogueAnswer } from "../lib/catalogue.js";
import { createCloudHandler } from "../lib/cloud.js";

test("after semantic planning, course counts use catalogue data without embeddings or generation", async () => {
  for (const total of [46, 47]) {
    let called = false;
    const source = {
      id: 1,
      url: "https://codehub.gr/training-programs/",
      title: "Training Programs",
      text: `${total} courses`,
    };
    const handler = createCloudHandler({
      env: { OPENAI_API_KEY: "test-only" },
      planQuery: async () => ({
        operation: "count",
        collection: "course",
        constrained: false,
        query: "total course catalogue",
        next_page: false,
        language: "el",
      }),
      getStore: () => ({
        snapshot: async () => ({ id: "snapshot" }),
        reserve: async () => true,
        catalogueCount: async (snapshot) => {
          assert.equal(snapshot.id, "snapshot");
          return { total, indexed_courses: total, source };
        },
        search: () =>
          assert.fail("A whole-catalogue count must not count search hits"),
      }),
      fetcher: async () => {
        called = true;
        assert.fail("No embeddings or generation for catalogue counts");
      },
    });
    const response = await handler(
      new Request("https://demo.test/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: [{ role: "user", content: "πόσα trainings υπάρχουν;" }],
        }),
      }),
    );
    const output = await response.text();
    assert.equal(called, false);
    assert.match(output, new RegExp(`${total} courses/`));
    assert.match(output, /training-programs/);
    assert.match(output, /\[1\]/);
    assert.match(output, /"mode":"catalogue"/);
  }
});

test("missing catalogue totals are acknowledged without inventing a count", () => {
  assert.match(catalogueAnswer(null, "How many courses?"), /couldn't verify/);
  assert.doesNotMatch(
    catalogueAnswer(null, "How many courses?"),
    /46|2 trainings/,
  );
});
