# Semantic query understanding in the Vercel API

The previous cloud router used word whitelists and then edit-distance matching to
choose catalogue operations. Those checks could reject a paraphrase or typo before
the semantic retriever ran. They have been removed, including `web/lib/jobs.js`.

## Implemented behavior

- `web/lib/planner.js` asks the configured Responses model for a strict JSON plan:
  search/list/count, collection, standalone query, constraints, continuation and language.
- The server validates the plan and permits only predefined read-only functions.
  The model cannot generate SQL or arbitrary actions.
- Constrained/unsupported whole-catalogue operations are forced into retrieval.
  The original current question is retained alongside the rewritten query; resolving
  conversation context no longer blindly appends the previous topic to every follow-up.
- Collection inference is not blindly applied as an exclusive search filter. A
  matching explicit UI filter is retained; otherwise retrieval remains broad.
- Job and course catalogues share SQL listing/pagination. Counts use the explicit
  catalogue total and a distinct-page count. Existing BM25/pgvector retrieval and
  grounded answer checks remain in place.
- The UI supports the next-page action for both jobs and courses. Page buttons
  retain the snapshot and bypass another language-planning call.
- New free-text questions add one metered model call. Reported response token usage
  includes planning plus grounding/generation; query embeddings are separate.

This is the Vercel Node API path. The separate local Python/E5 preview retains its
own orchestration; this report does not claim identical local/cloud behavior.

## Real model evaluation

The development set contains 36 cases: known regressions plus paraphrases, Greeklish,
typos, counts, listings, constrained questions, exact technology names and follow-ups.
The first run passed 31/36 complete annotations, while all 36 primary operation
choices were correct. Failures concerned collection choice, a dropped negative
technology term and response language. The prompt was refined using these results.

The second run passed **36/36** complete annotations. It consumed 20,334 input and
1,984 output tokens. These are development results from one run after tuning on the
same set, not a held-out accuracy estimate or a guarantee for arbitrary questions.

- [Cases](../evaluation/intent-questions.jsonl)
- [Initial run](intent-planning-baseline.json)
- [Final run](intent-planning-smoke.json)

Reproduce from the repository root with Node 24 and a local server-side key:

```powershell
node --env-file=.env web/scripts/evaluate-planner.mjs --output data/cloud/intent-evaluation.json
```

This command makes paid API calls. It does not modify the corpus or rebuild indexes.

## Integration verification and limits

Real Neon checks confirmed 61 indexed job URLs and 46 indexed course URLs, with
matching catalogue totals and working next-page metadata for both collections.
The PostgreSQL test fixture also covered both collections and snapshot lookup.

Seven local Node HTTP-flow checks against real Neon/OpenAI completed: Greeklish job
browsing, Greeklish course count, course browsing, a semantic job-page continuation,
contact details, a phone follow-up, and a constrained Python/Athens query. The first
six produced the expected catalogue/source-backed response. The constrained query
abstained because the evidence check did not establish the requested answer; it is
not counted as a successful job-match answer. The smoke script's mode checks alone
do not measure factual correctness or complete filtered-query recall.

Routing correctness does not establish retrieval quality or factual accuracy.
Filtered inventories/exact counts still require supported evidence; the system must
not turn the count of a small retrieved subset into a full-site count. An independent
retrieval/answer evaluation and broader extraction quality audit remain necessary.

References: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[OpenAI embeddings](https://developers.openai.com/api/docs/guides/embeddings).
