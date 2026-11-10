import test from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import handler from "../api/[route].js";

await test("proxy rejects unknown routes, wrong methods and missing configuration", async () => {
  assert.equal(
    (await handler.fetch(new Request("https://demo.test/api/unknown"))).status,
    404,
  );
  assert.equal(
    (await handler.fetch(new Request("https://demo.test/api/chat"))).status,
    405,
  );
  delete process.env.RAG_API_URL;
  delete process.env.RAG_API_TOKEN;
  assert.equal(
    (await handler.fetch(new Request("https://demo.test/api/status"))).status,
    503,
  );
});

await test("proxy preserves SSE streaming and keeps backend credentials private", async () => {
  let release;
  const continueStream = new Promise((resolve) => {
    release = resolve;
  });
  let authorization;
  const upstream = createServer(async (request, response) => {
    authorization = request.headers.authorization;
    response.writeHead(200, { "Content-Type": "text/event-stream" });
    response.write('event: sources\ndata: {"sources":[]}\n\n');
    await continueStream;
    response.end('event: done\ndata: {"mode":"openai"}\n\n');
  });
  await new Promise((resolve) => upstream.listen(0, "127.0.0.1", resolve));
  process.env.RAG_API_URL = `http://127.0.0.1:${upstream.address().port}`;
  process.env.RAG_API_TOKEN = "test-backend-secret";
  delete process.env.VERCEL;
  try {
    const response = await handler.fetch(
      new Request("https://demo.test/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: '{"messages":[]}',
      }),
    );
    assert.equal(response.status, 200);
    const reader = response.body.getReader();
    const first = new TextDecoder().decode((await reader.read()).value);
    assert.match(first, /event: sources/);
    assert.equal(authorization, "Bearer test-backend-secret");
    assert.doesNotMatch(first, /test-backend-secret/);
    release();
    let rest = "";
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      rest += new TextDecoder().decode(part.value);
    }
    assert.match(rest, /event: done/);
  } finally {
    release();
    await new Promise((resolve) => upstream.close(resolve));
  }
});

await test("proxy rejects invalid JSON, large bodies and insecure production origins", async () => {
  process.env.RAG_API_URL = "https://example.test";
  process.env.RAG_API_TOKEN = "test-secret";
  const request = (body) =>
    new Request("https://demo.test/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
  assert.equal((await handler.fetch(request("not json"))).status, 400);
  assert.equal((await handler.fetch(request("x".repeat(32769)))).status, 413);
  process.env.RAG_API_URL = "http://127.0.0.1:8000";
  process.env.VERCEL = "1";
  assert.equal(
    (await handler.fetch(new Request("https://demo.test/api/status"))).status,
    502,
  );
  delete process.env.VERCEL;
});
