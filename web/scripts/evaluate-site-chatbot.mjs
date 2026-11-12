import { readFile, writeFile, mkdir } from "node:fs/promises";
import { createCloudHandler } from "../lib/cloud.js";
import { createStore, database } from "../lib/store.js";
import { resolve, dirname } from "node:path";

// Real, metered end-to-end calls. No application prompts/indexes are changed.
// Run public first. --local-remaining completes only rate-limited/unattempted cases
// using the same handler, real Neon and OpenAI, with a budget equal to the case count.
const option = (name, fallback) =>
  process.argv.includes(name)
    ? process.argv[process.argv.indexOf(name) + 1]
    : fallback;
const resume =
  process.argv.includes("--local-remaining") ||
  process.argv.includes("--resume");
const local =
  process.argv.includes("--local-remaining") ||
  process.argv.includes("--local");
const cases = JSON.parse(
  await readFile(
    option(
      "--cases",
      new URL("../../evaluation/site-chatbot-30.json", import.meta.url),
    ),
    "utf8",
  ),
);
const output = resolve(option("--output", "data/cloud/site-chatbot-30.json"));
await mkdir(dirname(output), { recursive: true });
const report = resume
  ? JSON.parse(await readFile(output, "utf8"))
  : {
      started_at: new Date().toISOString(),
      endpoint: "https://codehub-rag.vercel.app/api/chat",
      status: await (
        await fetch("https://codehub-rag.vercel.app/api/status")
      ).json(),
      rows: [],
    };
if (process.argv.includes("--local-remaining"))
  report.public_attempts ??= report.rows.map(
    ({ id, http_status, completed, latency_ms }) => ({
      id,
      http_status,
      completed,
      latency_ms,
    }),
  );
let localCalls = 0,
  stopPublic = false;
const store = local ? createStore(database()) : null;
const handler = local
  ? createCloudHandler({
      getStore: () => ({
        ...store,
        reserve: async () => ++localCalls <= cases.length,
      }),
    })
  : null;
if (local) {
  report.local_status = await (
    await handler(new Request("https://evaluation.test/api/status"))
  ).json();
  if (!resume) report.status = report.local_status;
  if (!report.local_status.ready) throw new Error("local_backend_not_ready");
}
let pendingWrite = Promise.resolve();
const persist = () => {
  const text = JSON.stringify(report, null, 2) + "\n";
  pendingWrite = pendingWrite.then(() => writeFile(output, text));
  return pendingWrite;
};
async function ask(item) {
  const previous = report.rows.find((r) => r.id === item.id);
  if (previous?.completed) return;
  if (stopPublic) return;
  const history = [];
  if (item.history_from) {
    const parent = report.rows.find((r) => r.id === item.history_from);
    if (!parent?.completed) return;
    history.push(
      { role: "user", content: parent.question },
      { role: "assistant", content: parent.answer },
    );
  }
  const messages = [...history, { role: "user", content: item.question }];
  const start = performance.now();
  const row = {
    ...item,
    transport: local ? "local-production-handler" : "public-vercel",
    messages,
    completed: false,
    answer: "",
    sources: [],
    source_events: [],
    events: [],
  };
  try {
    const options = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages }),
      signal: AbortSignal.timeout(105000),
    };
    const response = local
      ? await handler(new Request("https://evaluation.test/api/chat", options))
      : await fetch(report.endpoint, options);
    row.http_status = response.status;
    const text = await response.text();
    if (response.status === 429 && !local) stopPublic = true;
    for (const frame of text.split(/\r?\n\r?\n/)) {
      const name = frame.match(/^event:\s*(.*)$/m)?.[1];
      const data = frame
        .split(/\r?\n/)
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (!data) continue;
      const parsed = JSON.parse(data);
      row.events.push({ event: name, data: parsed });
      if (name === "delta") row.answer += parsed.text;
      if (name === "sources") {
        row.sources = parsed.sources;
        row.source_events.push(parsed.sources);
      }
      if (name === "done") {
        row.completed = true;
        row.done = parsed;
      }
      if (name === "error") row.error = parsed.code;
    }
  } catch (error) {
    row.error = error.constructor.name;
  }
  row.latency_ms = Math.round(performance.now() - start);
  if (previous) report.rows[report.rows.indexOf(previous)] = row;
  else report.rows.push(row);
  await persist();
  console.log(
    JSON.stringify({
      id: row.id,
      transport: row.transport,
      status: row.http_status,
      completed: row.completed,
      sources: row.sources.length,
      mode: row.done?.mode,
      error: row.error,
      latency_ms: row.latency_ms,
    }),
  );
}
try {
  // Two concurrent independent questions; follow-ups wait for the real parent.
  const independent = cases.filter((item) => !item.history_from);
  for (let i = 0; i < independent.length; i += 2)
    await Promise.all(independent.slice(i, i + 2).map(ask));
  for (const item of cases.filter((item) => item.history_from)) await ask(item);
  report.finished_at = new Date().toISOString();
  await persist();
  console.log(
    JSON.stringify({
      completed: report.rows.filter((r) => r.completed).length,
      total: cases.length,
      public_rate_limited: stopPublic,
      local_calls: localCalls,
    }),
  );
} finally {
  if (local) await database().end();
}
