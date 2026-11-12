import test from "node:test";
import assert from "node:assert/strict";
import { courseFacts, eligibleCourses } from "../lib/learning.js";
import { createCloudHandler, validate } from "../lib/cloud.js";

const snapshot = { id: "a".repeat(64), config: { parent_documents: true } };
const pages = [
  {
    id: 10,
    title: "RAG",
    url: "https://codehub.gr/course/rag/",
    text: "RAG\nDuration: 24 Hours\nDifficulty Level: Intermediate\nAudience: Professionals",
    categories: ["course"],
  },
  {
    id: 20,
    title: "Python",
    url: "https://codehub.gr/course/python/",
    text: "Python\nDuration: 88 Hours\nDifficulty Level: Advanced",
    categories: ["course"],
  },
];
const events = (text) =>
  text
    .trim()
    .split("\n\n")
    .map((block) => ({
      type: block.split("\n")[0].slice(7),
      data: JSON.parse(block.split("\ndata: ")[1]),
    }));
const request = (payload) =>
  new Request("https://demo.test/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
const advisor = {
  goal: "Build a RAG app",
  background: "Python beginner",
  max_hours: 24,
};

test("course facts use labeled source fields; unknown durations never satisfy a ceiling", () => {
  assert.equal(courseFacts(pages[0]).hours, 24);
  assert.equal(courseFacts(pages[0]).level, "Intermediate");
  const unknown = {
    ...pages[0],
    text: "Learn Python in 6 weeks with 24 tools",
  };
  assert.equal(courseFacts(unknown).hours, null);
  const zero = { ...pages[0], text: "Duration: 0 Hours" };
  assert.equal(courseFacts(zero).hours, null);
  assert.equal(eligibleCourses([zero], 8).length, 0);
  assert.deepEqual(
    eligibleCourses([...pages, unknown], 24).map((p) => p.title),
    ["RAG"],
  );
  assert.equal(eligibleCourses([...pages, unknown], null).length, 3);
});
test("learning actions reject foreign URLs, duplicates, oversized profiles and incompatible actions", () => {
  const payload = { messages: [{ role: "user", content: "Compare" }], advisor };
  assert.equal(validate(payload).advisor.max_hours, 24);
  const explore = {
    type: "compare",
    urls: pages.map((p) => p.url),
    snapshot_id: snapshot.id,
  };
  assert.deepEqual(
    validate({ ...payload, explore }).explore.urls,
    explore.urls,
  );
  for (const urls of [
    [pages[0].url, pages[0].url],
    [pages[0].url, "https://evil.test/course/x/"],
    [pages[0].url],
  ])
    assert.throws(() =>
      validate({ ...payload, explore: { ...explore, urls } }),
    );
  assert.throws(() =>
    validate({ ...payload, advisor: { ...advisor, goal: "x".repeat(501) } }),
  );
  assert.throws(() =>
    validate({ ...payload, advisor: { ...advisor, max_hours: -24 } }),
  );
  assert.throws(() =>
    validate({ ...payload, explore, listing: { kind: "course", offset: 0 } }),
  );
});
function provider() {
  let calls = 0;
  return async (url, options) => {
    assert.match(url, /responses$/);
    const body = JSON.parse(options.body);
    const input = JSON.parse(body.input.at(-1).content);
    assert.deepEqual(
      input.WEBSITE_EVIDENCE.map((s) => s.title),
      ["RAG", "Python"],
    );
    if (++calls === 1)
      return Response.json({
        status: "completed",
        output: [
          {
            type: "message",
            content: [
              {
                type: "output_text",
                text: JSON.stringify({
                  answerable: true,
                  source_ids: [1, 2],
                  reason: "supported",
                }),
              },
            ],
          },
        ],
      });
    assert.match(body.instructions, /visitor actually declared/);
    return new Response(
      [
        {
          type: "response.output_text.delta",
          delta: "RAG 24 hours [1]; Python 88 hours [2].",
        },
        {
          type: "response.completed",
          response: { usage: { input_tokens: 20, output_tokens: 10 } },
        },
      ]
        .map((e) => `data: ${JSON.stringify(e)}\n\n`)
        .join(""),
    );
  };
}
test("comparison pins two real course pages, skips retrieval, emits sourced facts and trace", async () => {
  let pinned;
  const handler = createCloudHandler({
    env: { OPENAI_API_KEY: "test" },
    getStore: () => ({
      snapshot: async (id) => {
        pinned = id;
        return snapshot;
      },
      reserve: async () => true,
      coursePages: async () => pages,
    }),
    planQuery: () => {
      throw new Error("Comparison must not reroute");
    },
    fetcher: provider(),
  });
  const response = await handler(
    request({
      messages: [{ role: "user", content: "Compare RAG and Python" }],
      explore: {
        type: "compare",
        urls: pages.map((p) => p.url),
        snapshot_id: snapshot.id,
      },
    }),
  );
  const output = events(await response.text());
  assert.equal(pinned, snapshot.id);
  assert.equal(output.at(-1).type, "done");
  const learning = output.find((e) => e.type === "learning").data;
  assert.deepEqual(
    learning.comparison.map((c) => c.hours),
    [24, 88],
  );
  assert.equal(learning.trace.consulted, 2);
  assert.equal(learning.trace.cited, 2);
  assert.equal(learning.cards.length, 2);
  assert.ok(learning.trace.total_ms >= 0);
});
test("unknown selected course fails without fabricating a comparison or calling the model", async () => {
  const handler = createCloudHandler({
    env: { OPENAI_API_KEY: "test" },
    getStore: () => ({
      snapshot: async () => snapshot,
      reserve: async () => true,
      coursePages: async () => [],
    }),
    fetcher: () => {
      throw new Error("No model calls allowed");
    },
  });
  const output = events(
    await (
      await handler(
        request({
          messages: [{ role: "user", content: "Compare" }],
          explore: {
            type: "compare",
            urls: pages.map((p) => p.url),
            snapshot_id: snapshot.id,
          },
        }),
      )
    ).text(),
  );
  assert.ok(output.some((e) => e.type === "error"));
  assert.ok(!output.some((e) => e.type === "learning"));
});
test("advisor duration is enforced before retrieval even when planner chooses an unfiltered list", async () => {
  let eligible;
  const handler = createCloudHandler({
    env: { OPENAI_API_KEY: "test" },
    getStore: () => ({
      snapshot: async () => snapshot,
      reserve: async () => true,
      coursePages: async () => pages,
      search: async (_s, _q, _v, _k, options) => {
        eligible = options.allowedUrls;
        return [];
      },
    }),
    planQuery: async () => ({
      operation: "list",
      collection: "course",
      constrained: false,
      next_page: false,
      query: "RAG courses",
      language: "en",
    }),
    fetcher: async (url) => {
      assert.match(url, /embeddings$/);
      return Response.json({ data: [{ embedding: Array(384).fill(0) }] });
    },
  });
  await (
    await handler(
      request({ messages: [{ role: "user", content: "Courses" }], advisor }),
    )
  ).text();
  assert.deepEqual(eligible, [pages[0].url]);
});

test("course prerequisites retain required and explicitly optional groups", () => {
  const source = {
    ...pages[0],
    text:
      pages[0].text +
      "\n\nPython > Prerequisite Knowledge\nSolid Python foundations\nBeneficial but not mandatory\nGit experience\nREST APIs\n\nPython > Delivery Format\nLive Online",
  };
  const facts = courseFacts(source);
  assert.equal(facts.required_prerequisites, "Solid Python foundations");
  assert.equal(facts.beneficial_prerequisites, "Git experience\nREST APIs");
  assert.doesNotMatch(facts.prerequisites, /Delivery Format/);
  assert.equal(courseFacts(pages[0]).required_prerequisites, null);
});
