import test from "node:test";
import assert from "node:assert/strict";
import { jobListIntent, jobListAnswer } from "../lib/jobs.js";
import { createCloudHandler, validate } from "../lib/cloud.js";

const source = {
  id: 1,
  title: "AI Developer | Code.Hub",
  url: "https://codehub.gr/job/po-123-ai-developer/",
  text: "AI developer role",
  categories: ["job"],
  warnings: [],
};
const snapshotId = "a".repeat(64);
const messages = (content) => [{ role: "user", content }];

test("broad careers questions request job listings; specific topics keep semantic search", () => {
  for (const q of [
    "ποιες ειναι οι καριέρες;",
    "ποιες εναι οι καριέρες?",
    "ποιες ειναι οι καριερες?",
    "ποιες εναι οι θεσεις εργασιας;",
    "Ποιες θέσεις εργασίας υπάρχουν;",
    "θέσεις εργασίας",
    "What jobs are available?",
    "List all careers",
    "careers",
  ]) {
    assert.deepEqual(jobListIntent(messages(q)), { kind: "job", offset: 0 }, q);
  }
  for (const q of [
    "Πώς μπορώ να αλλάξω καριέρα;",
    "What jobs are available in Athens?",
    "Python jobs",
    "Ποιες είναι οι θέσεις στην Αθήνα;",
    "Ποιες είναι οι θέσεις για Java;",
    "What salary do jobs pay?",
    "How many trainings are there?",
  ]) {
    assert.equal(jobListIntent(messages(q)), null, q);
  }
});

test("natural-language requests for more jobs continue after the previous page", () => {
  const request = [
    { role: "user", content: "Careers?" },
    { role: "assistant", content: "**Θέσεις 1–10 από 61**:\n- Role [1]" },
    { role: "user", content: "Δείξε τις επόμενες θέσεις εργασίας." },
  ];
  assert.deepEqual(jobListIntent(request), { kind: "job", offset: 10 });
  assert.equal(jobListIntent(messages("More")), null);
});

test("job listing responses have actual links and no paid provider calls", async () => {
  let requestedOffset, pinned;
  const next = { kind: "job", offset: 20, snapshot_id: snapshotId };
  const handler = createCloudHandler({
    env: { OPENAI_API_KEY: "test-only" },
    getStore: () => ({
      snapshot: async (id) => {
        pinned = id;
        return { id: snapshotId };
      },
      reserve: async () => true,
      listJobs: async (_snapshot, offset) => {
        requestedOffset = offset;
        return { total: 61, offset, sources: [source], next };
      },
      search: () =>
        assert.fail("A general jobs list must not sample semantic search hits"),
    }),
    fetcher: () => assert.fail("Job inventory listing must not call OpenAI"),
  });
  const response = await handler(
    new Request("https://demo.test/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: messages("Δείξε τις επόμενες θέσεις εργασίας."),
        listing: { kind: "job", offset: 10, snapshot_id: snapshotId },
      }),
    }),
  );
  const output = await response.text();
  assert.equal(response.status, 200);
  assert.equal(pinned, snapshotId);
  assert.equal(requestedOffset, 10);
  assert.match(output, /AI Developer/);
  assert.match(output, /PO-123/);
  assert.match(output, /po-123-ai-developer/);
  assert.match(output, /\[1\]/);
  assert.match(output, /"mode":"job-list"/);
  assert.match(output, /"next_listing"/);
});

test("pagination inputs are bounded and empty inventories don't invent jobs", () => {
  for (const listing of [
    { kind: "job", offset: -1 },
    { kind: "job", offset: 1e9 },
    { kind: "admin", offset: 0 },
    { kind: "job", offset: 0, snapshot_id: "invalid" },
  ]) {
    assert.throws(() => validate({ messages: messages("Careers"), listing }));
  }
  assert.match(jobListAnswer({ sources: [] }, "Careers"), /couldn't find/);
});
