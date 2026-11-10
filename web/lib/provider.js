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

export async function* answer(payload, sources, env, signal, fetcher = fetch) {
  const model = env.OPENAI_MODEL || "gpt-6-luna";
  const history = payload.messages.slice(-9, -1);
  const evidence = sources.map((s) => ({
    source: s.id,
    url: s.url,
    title: s.title,
    fetched_at: s.fetched_at,
    warnings: s.warnings,
    text: s.text.slice(0, 4500),
  }));
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
          content: JSON.stringify({
            question: payload.messages.at(-1).content,
            today_utc: new Date().toISOString().slice(0, 10),
            WEBSITE_EVIDENCE: evidence,
          }),
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
  let wroteText = false;
  for await (const update of readEvents(response.body)) {
    if (update.type === "response.output_text.delta") {
      if (typeof update.delta !== "string") throw new Error("invalid_delta");
      wroteText ||= update.delta.length > 0;
      yield ["delta", { text: update.delta }];
    } else if (update.type === "response.completed") {
      if (!wroteText) throw new Error("empty_answer");
      const usage = update.response?.usage;
      yield [
        "done",
        {
          mode: "openai",
          usage: usage
            ? {
                input_tokens: usage.input_tokens,
                output_tokens: usage.output_tokens,
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
