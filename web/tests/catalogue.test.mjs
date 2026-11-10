import test from "node:test";
import assert from "node:assert/strict";
import { isCatalogueCount, catalogueAnswer } from "../lib/catalogue.js";
import { createCloudHandler } from "../lib/cloud.js";

test("general Trainings counts mean the course catalogue, not scheduled events", () => {
  for (const question of [
    "πόσα trainings υπάρχουν;",
    "Πόσα courses έχετε;",
    "Πόσα μαθήματα υπάρχουν συνολικά;",
    "How many trainings are there?",
    "How many training programmes does Code.Hub offer?",
    "What is the total number of courses?",
  ])
    assert.equal(isCatalogueCount(question), true, question);
  for (const question of [
    "Πόσα trainings για Python υπάρχουν;",
    "How many AWS courses are there?",
    "How many open trainings are there?",
    "Πόσα προγραμματισμένα trainings υπάρχουν;",
    "Πόσα trainings έγιναν το 2024;",
    "How many jobs are there?",
    "Tell me about training",
  ])
    assert.equal(isCatalogueCount(question), false, question);
});

test("course count comes from catalogue data and does not trigger paid provider calls", async () => {
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
