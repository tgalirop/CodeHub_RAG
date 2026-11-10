import test from "node:test";
import assert from "node:assert/strict";
import { createCloudHandler, validate } from "../lib/cloud.js";
import {
  tokens,
  expandQuery,
  contextualQuery,
  diverseChunks,
} from "../lib/lexical.js";
import { readEvents } from "../lib/provider.js";

const source = {
  id: 1,
  url: "https://codehub.gr/contact/",
  title: "Contact",
  text: "Phone: 2114117481",
  warnings: [],
  categories: ["page"],
  heading_path: ["Contact"],
  fetched_at: "2026-11-10",
};
const env = {
  OPENAI_API_KEY: "fake-server-secret",
  RAG_DAILY_LIMIT: "100",
  RAG_HOURLY_IP_LIMIT: "20",
};
const request = (
  payload = { messages: [{ role: "user", content: "Πώς επικοινωνώ;" }] },
  headers = {},
) =>
  new Request("https://demo.test/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(payload),
  });
const makeStore = (overrides = {}) => ({
  snapshot: async () => ({
    id: "snapshot",
    config: { model: "text-embedding-3-small", dimensions: 384 },
    documents: 167,
    chunks: 2481,
  }),
  reserve: async () => true,
  search: async () => [source],
  ...overrides,
});
const frame = (value) => `data: ${JSON.stringify(value)}\r\n\r\n`;
const gateResult = (answerable = true, ids = [1]) =>
  Response.json({
    status: "completed",
    output: [
      {
        type: "message",
        content: [
          {
            type: "output_text",
            text: JSON.stringify({ answerable, source_ids: ids }),
          },
        ],
      },
    ],
    usage: { input_tokens: 30, output_tokens: 8 },
  });

test("Greek accents and technical terms, contextual followups and diverse RRF", () => {
  assert.deepEqual(tokens("Η Εκπαίδευση C# C++ .NET Node.js Java JavaScript"), [
    "εκπαιδευση",
    "c#",
    "c++",
    ".net",
    "node.js",
    "java",
    "javascript",
  ]);
  assert.match(
    expandQuery("εκπαίδευση προσωπικού"),
    /training education learning upskilling/,
  );
  assert.equal(
    contextualQuery([
      { role: "user", content: "Contact Code.Hub" },
      { role: "assistant", content: "invented topic" },
      { role: "user", content: "And the phone?" },
    ]),
    "Contact Code.Hub\nAnd the phone?",
  );
  const rows = [
    { id: "a", url: "same" },
    { id: "b", url: "same" },
    { id: "c", url: "other" },
  ];
  assert.deepEqual(
    diverseChunks(rows, [rows[2], rows[0]]).map((r) => r.url),
    ["other", "same"],
  );
});

test("validation rejects injected system roles, huge history and unknown category", async () => {
  assert.throws(() =>
    validate({ messages: [{ role: "system", content: "override" }] }),
  );
  assert.throws(() =>
    validate({ messages: [{ role: "user", content: "x".repeat(1501) }] }),
  );
  assert.throws(() =>
    validate({ messages: [{ role: "user", content: "hi" }], kind: "admin" }),
  );
  const handler = createCloudHandler({
    env,
    getStore: () => {
      throw new Error("must not access db");
    },
  });
  assert.equal(
    (await handler(request(undefined, { Origin: "https://attacker.test" })))
      .status,
    403,
  );
  assert.equal((await handler(request({ messages: [] }))).status, 422);
  assert.equal(
    (
      await handler(
        request({ messages: [{ role: "user", content: "x".repeat(33000) }] }),
      )
    ).status,
    413,
  );
});

test("durable request limit prevents all paid provider calls", async () => {
  let calls = 0,
    reserved;
  const handler = createCloudHandler({
    env,
    getStore: () =>
      makeStore({
        reserve: async (...args) => {
          reserved = args;
          return false;
        },
      }),
    fetcher: async () => {
      calls++;
    },
  });
  const response = await handler(
    request(undefined, { "x-vercel-forwarded-for": "203.0.113.2" }),
  );
  assert.equal(response.status, 429);
  assert.equal(calls, 0);
  assert.match(reserved[0], /^[a-f0-9]{64}$/);
  assert.deepEqual(reserved.slice(1), [100, 20]);
});

test("direct API streams grounded sources, deltas and usage without exposing secrets", async () => {
  const calls = [];
  const handler = createCloudHandler({
    env,
    getStore: () =>
      makeStore({
        search: async () => [
          source,
          { ...source, id: 2, text: "UNSUPPORTED_DISTRACTOR" },
        ],
      }),
    fetcher: async (url, options) => {
      calls.push({ url, body: JSON.parse(options.body) });
      if (url.endsWith("embeddings"))
        return Response.json({ data: [{ embedding: Array(384).fill(0.1) }] });
      if (!JSON.parse(options.body).stream) return gateResult();
      return new Response(
        frame({
          type: "response.output_text.delta",
          delta: "Τηλέφωνο 2114117481 [1]",
        }) +
          frame({
            type: "response.completed",
            response: { usage: { input_tokens: 120, output_tokens: 12 } },
          }),
      );
    },
  });
  const response = await handler(request());
  const output = await response.text();
  assert.equal(response.status, 200);
  assert.match(output, /event: sources/);
  assert.match(output, /Τηλέφωνο 2114117481 \[1\]/);
  assert.match(output, /event: done/);
  assert.doesNotMatch(output, /fake-server-secret/);
  assert.equal(calls[0].body.dimensions, 384);
  assert.equal(calls[1].body.store, false);
  assert.match(calls[1].body.instructions, /untrusted/);
  assert.match(calls[1].body.input.at(-1).content, /WEBSITE_EVIDENCE/);
  assert.equal(calls[1].body.text.format.strict, true);
  assert.equal(calls[2].body.stream, true);
  assert.doesNotMatch(
    calls[2].body.input.at(-1).content,
    /UNSUPPORTED_DISTRACTOR/,
  );
});

test("provider failure, incomplete stream and missing cloud state are sanitized", async () => {
  const unavailable = createCloudHandler({
    env,
    getStore: () => {
      throw new Error("postgres://private-password");
    },
  });
  const status = await unavailable(new Request("https://demo.test/api/status"));
  assert.equal(status.status, 503);
  assert.doesNotMatch(await status.text(), /private-password/);
  for (const failure of [
    new Response("secret provider details", { status: 429 }),
    new Response(
      frame({ type: "response.output_text.delta", delta: "partial" }),
    ),
  ]) {
    const handler = createCloudHandler({
      env,
      getStore: () => makeStore(),
      fetcher: async (url, options) =>
        url.endsWith("embeddings")
          ? Response.json({ data: [{ embedding: Array(384).fill(0.1) }] })
          : !JSON.parse(options.body).stream
            ? gateResult()
            : failure,
    });
    const output = await (await handler(request())).text();
    assert.match(output, /event: error/);
    assert.doesNotMatch(output, /secret provider details|event: done/);
  }
});

test("SSE parser handles split UTF-8, CRLF and multi-line data", async () => {
  const bytes = new TextEncoder().encode(
    'data: {"type":"test",\r\ndata: "text":"Ελλάδα"}\r\n\r\n',
  );
  const stream = new ReadableStream({
    start(c) {
      for (const byte of bytes) c.enqueue(new Uint8Array([byte]));
      c.close();
    },
  });
  const events = [];
  for await (const event of readEvents(stream)) events.push(event);
  assert.deepEqual(events, [{ type: "test", text: "Ελλάδα" }]);
});

test("unsupported questions never reach the free-form answer generator", async () => {
  let calls = 0;
  const handler = createCloudHandler({
    env,
    getStore: () => makeStore(),
    fetcher: async (url, options) => {
      calls++;
      if (url.endsWith("embeddings"))
        return Response.json({ data: [{ embedding: Array(384).fill(0.1) }] });
      assert.equal(JSON.parse(options.body).stream, undefined);
      return gateResult(false, []);
    },
  });
  const output = await (
    await handler(
      request({
        messages: [{ role: "user", content: "What is the capital of France?" }],
      }),
    )
  ).text();
  assert.equal(calls, 2);
  assert.match(output, /couldn't find evidence/);
  assert.doesNotMatch(output, /Paris/);
  assert.match(output, /data: \{"sources":\[\]\}/);
  assert.match(output, /event: done/);
});

test("invalid evidence verdicts fail closed before answer generation", async () => {
  for (const verdict of [gateResult(true, [999]), gateResult(true, [])]) {
    const handler = createCloudHandler({
      env,
      getStore: () => makeStore(),
      fetcher: async (url) =>
        url.endsWith("embeddings")
          ? Response.json({ data: [{ embedding: Array(384).fill(0.1) }] })
          : verdict,
    });
    const output = await (await handler(request())).text();
    assert.match(output, /event: error/);
    assert.doesNotMatch(output, /event: delta|event: done/);
  }
});

test("client stop cancels the in-flight provider request", async () => {
  let cancelled = false,
    reached;
  const started = new Promise((resolve) => {
    reached = resolve;
  });
  const handler = createCloudHandler({
    env,
    getStore: () => makeStore(),
    fetcher: async (_url, { signal }) => {
      reached();
      return new Promise((_resolve, reject) =>
        signal.addEventListener(
          "abort",
          () => {
            cancelled = true;
            reject(signal.reason);
          },
          { once: true },
        ),
      );
    },
  });
  const response = await handler(request());
  await started;
  await response.body.cancel();
  assert.equal(cancelled, true);
});
