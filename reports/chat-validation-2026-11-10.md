# Chatbot validation — 2026-11-10

## Implemented

The local UI is served at `http://127.0.0.1:8000` by FastAPI. It uses the existing
hybrid retrieval snapshot and streams grounded answers through OpenAI Responses.
The default model is `gpt-6-luna`, verified as available to the configured account.
No credentials are included in this report or the frontend.

The UI includes Code.Hub's original logo and palette, suggested questions,
category filters, streaming text, numbered citations, expandable source cards,
browser-local conversations, stop, retry and copy controls. Responsive styles and
keyboard interactions are implemented, but visual/browser QA was not completed.

For Vercel, the `web` directory contains static assets and a Node.js 24 streaming
relay. A separate FastAPI container retains the existing local model and BM25
artifacts. No public deployment was provisioned. See [deployment](../docs/deployment.md).

## Automated and runtime checks

- **39 Python unit tests passed**; database tests are opt-in in the default test run.
- **6 PostgreSQL integration tests passed** on the dedicated `_test` database.
- **3 Node.js proxy tests passed**, including true streaming and secret separation.
- Ruff lint/format, JavaScript syntax and static build validation passed.
- Docker image built successfully and ran as a non-root Linux service.
- That container loaded the existing Windows-created snapshot through the portable
  artifact-root override: **167 eligible pages, 2,481 chunks**, status ready.
- The container served the UI with HTTP 200. It was stopped after validation;
  the native local server remains running on port 8000.

## Live OpenAI checks

Using the key stored only in the local `.env`:

1. A Greek contact question returned the published phone, email and office
   addresses with citation `[1]` to `https://codehub.gr/contact/`.
2. A follow-up asking for the phone number retained the topic and returned the
   published number with a source citation.
3. An unrelated capital-of-France question did not receive a general-knowledge
   answer; the assistant stated that the website did not establish it.

All three streams completed without errors. These are smoke checks, not a held-out
answer-quality evaluation or a guarantee of factual correctness. Date/status/source
warnings remain important for time-sensitive training and job information.

## Verification limit

Computer Use stopped the attempted Chrome preview because it could not determine
the current Windows browser URL with enough confidence to enforce its policy.
No alternative browser-control method was used. The local HTTP/API behavior was
verified, but desktop/mobile visual appearance, focus behavior and client-side
click flows still need manual browser review.

Primary references: [Responses streaming](https://developers.openai.com/api/docs/guides/streaming-responses),
[model catalog](https://developers.openai.com/api/docs/models),
[Vercel Node.js](https://vercel.com/docs/functions/runtimes/node-js),
[function limits](https://vercel.com/docs/functions/limitations).
