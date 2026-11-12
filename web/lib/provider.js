import {
  gateRequest,
  parseVerdict,
  evidenceInput,
  unsupportedAnswer,
} from "./grounding.js";
import { citedSources } from "../public/citations.js";

export class ProviderError extends Error {
  constructor(status) {
    super("provider_unavailable");
    this.status = status;
  }
}
export async function embed(query, key, signal, fetcher = fetch) {
  const response = await fetcher("https://api.openai.com/v1/embeddings", {
    method: "POST",
    signal,
    headers: {
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "text-embedding-3-small",
      dimensions: 384,
      input: query,
    }),
  });
  if (!response.ok) {
    await response.body?.cancel();
    throw new ProviderError(response.status);
  }
  const data = await response.json();
  const vector = data.data?.[0]?.embedding;
  if (
    !Array.isArray(vector) ||
    vector.length !== 384 ||
    !vector.every(Number.isFinite)
  )
    throw new Error("embedding_invalid");
  return vector;
}

export async function* readEvents(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) {
        finished = true;
        break;
      }
      buffer += decoder.decode(part.value, { stream: true });
      if (buffer.length > 1_000_000)
        throw new Error("provider_frame_too_large");
      let boundary;
      while ((boundary = buffer.match(/\r?\n\r?\n/))) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const data = frame
          .split(/\r?\n/)
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (data && data !== "[DONE]") yield JSON.parse(data);
      }
    }
  } finally {
    if (!finished) await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export async function* answer(
  payload,
  sources,
  env,
  signal,
  fetcher = fetch,
  recoverEvidence = null,
) {
  const model = env.OPENAI_MODEL || "gpt-6-luna";
  const history = payload.messages.slice(-9, -1);
  const gateResponse = await fetcher("https://api.openai.com/v1/responses", {
    method: "POST",
    signal,
    headers: {
      Authorization: `Bearer ${env.OPENAI_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(gateRequest(payload, sources, model)),
  });
  if (!gateResponse.ok) {
    await gateResponse.body?.cancel();
    throw new ProviderError(gateResponse.status);
  }
  let verdict = parseVerdict(await gateResponse.json(), sources);
  if (
    !verdict.answerable &&
    verdict.reason !== "out_of_scope" &&
    recoverEvidence
  ) {
    const recovered = await recoverEvidence();
    signal.throwIfAborted();
    if (recovered.length) {
      sources = recovered;
      yield ["sources", { sources }];
      const retry = await fetcher("https://api.openai.com/v1/responses", {
        method: "POST",
        signal,
        headers: {
          Authorization: `Bearer ${env.OPENAI_API_KEY}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(gateRequest(payload, sources, model)),
      });
      if (!retry.ok) {
        await retry.body?.cancel();
        throw new ProviderError(retry.status);
      }
      const next = parseVerdict(await retry.json(), sources);
      next.usage = {
        input_tokens:
          (next.usage?.input_tokens || 0) + (verdict.usage?.input_tokens || 0),
        output_tokens:
          (next.usage?.output_tokens || 0) +
          (verdict.usage?.output_tokens || 0),
      };
      verdict = next;
    }
  }
  if (!verdict.answerable) {
    yield ["sources", { sources: [] }];
    yield [
      "delta",
      { text: unsupportedAnswer(payload.messages.at(-1).content) },
    ];
    yield [
      "done",
      {
        mode: "openai",
        usage: verdict.usage
          ? {
              input_tokens: verdict.usage.input_tokens,
              output_tokens: verdict.usage.output_tokens,
            }
          : null,
      },
    ];
    return;
  }
  const supported = [...new Set(verdict.source_ids)]
    .slice(0, 10)
    .map((id, index) => ({
      ...sources.find((s) => s.id === id),
      id: index + 1,
    }));
  // Give generation a contiguous source namespace and publish that same mapping
  // before any token is streamed. No inference/remapping of hallucinated IDs.
  yield ["sources", { sources: supported }];
  const { default: config } = await import("./chat-config.json", {
    with: { type: "json" },
  });
  const response = await fetcher("https://api.openai.com/v1/responses", {
    method: "POST",
    signal,
    headers: {
      Authorization: `Bearer ${env.OPENAI_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model,
      instructions: config.instructions,
      input: [
        ...history,
        {
          role: "user",
          content: JSON.stringify(evidenceInput(payload, supported)),
        },
      ],
      stream: true,
      store: false,
      max_output_tokens: 2000,
      ...(/^(gpt-[56]|o[134])/.test(model)
        ? { reasoning: { effort: "low" } }
        : {}),
    }),
  });
  if (!response.ok) {
    await response.body?.cancel();
    throw new ProviderError(response.status);
  }
  let text = "";
  for await (const update of readEvents(response.body)) {
    if (update.type === "response.output_text.delta") {
      if (typeof update.delta !== "string") throw new Error("invalid_delta");
      text += update.delta;
      yield ["delta", { text: update.delta }];
    } else if (update.type === "response.completed") {
      if (!text) throw new Error("empty_answer");
      yield ["sources", { sources: citedSources(text, supported) }];
      const usage = update.response?.usage;
      yield [
        "done",
        {
          mode: "openai",
          usage: usage
            ? {
                input_tokens:
                  usage.input_tokens + (verdict.usage?.input_tokens || 0),
                output_tokens:
                  usage.output_tokens + (verdict.usage?.output_tokens || 0),
              }
            : null,
        },
      ];
      return;
    } else if (
      ["error", "response.failed", "response.incomplete"].includes(update.type)
    ) {
      throw new Error("generation_failed");
    }
  }
  throw new Error("stream_incomplete");
}
