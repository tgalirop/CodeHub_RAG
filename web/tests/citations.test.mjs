import test from "node:test";
import assert from "node:assert/strict";
import { citedSources, numberedCitations } from "../public/citations.js";
import { answer } from "../lib/provider.js";

const sources = [1, 2, 3].map((id) => ({
  id,
  title: `Page ${id}`,
  url: `https://codehub.gr/${id}/`,
  text: `Source ${id}`,
  warnings: [],
}));

test("only known citations are shown, without duplicates or renumbering", () => {
  assert.deepEqual(
    citedSources(
      "Fact [3]. Another [1], again [3], unknown [99].",
      sources,
    ).map((s) => s.id),
    [3, 1],
  );
  assert.deepEqual(citedSources("No citations here.", sources), []);
  assert.deepEqual(citedSources("A partial citation [3", sources), []);
  assert.deepEqual(citedSources("Fact [1]", null), []);
});

test("citation examples inside inline/fenced code are not counted", () => {
  const text =
    "Example `[1]`, unfinished `[2]\n```json\n[2]\n```\nSupported fact [3].";
  assert.deepEqual(
    citedSources(text, sources).map((s) => s.id),
    [3],
  );
});

test("display labels follow first mention and preserve evidence identity", () => {
  const evidence = [1, 2, 3, 4, 5].map((id) => ({
    id,
    url: `https://codehub.gr/${id}/`,
  }));
  const raw = "Training [2]. Skills [5]. Contact [1]. Again [2]. Unknown [99].";
  const result = numberedCitations(raw, evidence);
  assert.equal(
    result.text,
    "Training [1]. Skills [2]. Contact [3]. Again [1]. Unknown [99].",
  );
  assert.deepEqual(
    result.sources.map((s) => [s.id, s.url]),
    [
      [1, "https://codehub.gr/2/"],
      [2, "https://codehub.gr/5/"],
      [3, "https://codehub.gr/1/"],
    ],
  );
  assert.deepEqual(
    evidence.map((s) => s.id),
    [1, 2, 3, 4, 5],
  );
  assert.equal(
    numberedCitations("Example `[2]`\n```\n[5]\n```\nFact [5]", evidence).text,
    "Example `[2]`\n```\n[5]\n```\nFact [1]",
  );
});

test("cloud completion sends only sources cited in the answer, not all approved evidence", async () => {
  const payload = { messages: [{ role: "user", content: "Contact details?" }] };
  const updates = [];
  const fetcher = async (_url, options) => {
    if (!JSON.parse(options.body).stream)
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
                  source_ids: [1, 2, 3],
                }),
              },
            ],
          },
        ],
      });
    return new Response(
      [
        { type: "response.output_text.delta", delta: "Contact [" },
        { type: "response.output_text.delta", delta: "3]." },
        {
          type: "response.completed",
          response: { usage: { input_tokens: 100, output_tokens: 8 } },
        },
      ]
        .map((value) => `data: ${JSON.stringify(value)}\n\n`)
        .join(""),
    );
  };
  for await (const update of answer(
    payload,
    sources,
    { OPENAI_API_KEY: "test-only" },
    new AbortController().signal,
    fetcher,
  ))
    updates.push(update);
  const selected = updates.findLast(([type]) => type === "sources")[1].sources;
  assert.deepEqual(
    selected.map((s) => s.id),
    [3],
  );
  assert.equal(updates.at(-1)[0], "done");
});
