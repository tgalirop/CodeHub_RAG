import { readFile, writeFile, mkdir } from "node:fs/promises";
import { dirname } from "node:path";
import { semanticPlan } from "../lib/planner.js";

if (!process.env.OPENAI_API_KEY)
  throw new Error(
    "Set OPENAI_API_KEY server-side before running this paid API evaluation",
  );
const output = process.argv.includes("--output")
  ? process.argv[process.argv.indexOf("--output") + 1]
  : "data/cloud/intent-evaluation.json";
const cases = (
  await readFile(
    new URL("../../evaluation/intent-questions.jsonl", import.meta.url),
    "utf8",
  )
)
  .trim()
  .split("\n")
  .map(JSON.parse);
const rows = Array(cases.length);
let cursor = 0;
const normalize = (s) =>
  s.toLowerCase().normalize("NFD").replace(/\p{M}/gu, "");
async function worker() {
  while (cursor < cases.length) {
    const index = cursor++,
      item = cases[index],
      start = performance.now();
    try {
      const plan = await semanticPlan(
        item,
        process.env,
        AbortSignal.timeout(30000),
      );
      const errors = Object.entries(item.expected)
        .filter(([key, value]) => plan[key] !== value)
        .map(([key]) => key);
      for (const alternatives of item.required_terms || [])
        if (
          !alternatives.some((term) =>
            normalize(plan.query).includes(normalize(term)),
          )
        )
          errors.push("query_missing:" + alternatives.join("|"));
      rows[index] = {
        id: item.id,
        question: item.messages.at(-1).content,
        expected: item.expected,
        plan,
        passed: errors.length === 0,
        errors,
        latency_ms: Math.round(performance.now() - start),
      };
    } catch (error) {
      rows[index] = {
        id: item.id,
        passed: false,
        error_type: error.constructor.name,
        latency_ms: Math.round(performance.now() - start),
      };
    }
  }
}
await Promise.all([worker(), worker(), worker()]);
const result = {
  label:
    "Query-understanding development smoke set; one run, not an independent guarantee",
  model: process.env.OPENAI_MODEL || "gpt-6-luna",
  total: rows.length,
  passed: rows.filter((r) => r.passed).length,
  input_tokens: rows.reduce(
    (n, r) => n + (r.plan?.usage?.input_tokens || 0),
    0,
  ),
  output_tokens: rows.reduce(
    (n, r) => n + (r.plan?.usage?.output_tokens || 0),
    0,
  ),
  rows,
};
await mkdir(dirname(output), { recursive: true });
await writeFile(output, JSON.stringify(result, null, 2) + "\n");
console.log(
  JSON.stringify({
    ...result,
    rows: undefined,
    failures: rows
      .filter((r) => !r.passed)
      .map((r) => ({ id: r.id, errors: r.errors, error_type: r.error_type })),
  }),
);
if (result.passed !== result.total) process.exitCode = 1;
