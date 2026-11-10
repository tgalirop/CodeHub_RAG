import { createHmac } from "node:crypto";
import { database, createStore } from "./store.js";
import { contextualQuery, expandQuery } from "./lexical.js";
import { embed, answer, ProviderError } from "./provider.js";
import { isCatalogueCount, catalogueAnswer } from "./catalogue.js";
import { jobListIntent, jobListAnswer } from "./jobs.js";

const HEADERS = {
  "Cache-Control": "no-store, no-transform",
  "X-Content-Type-Options": "nosniff",
};
const json = (data, status = 200) =>
  Response.json(data, { status, headers: HEADERS });
export function validate(payload) {
  if (
    !payload ||
    !Array.isArray(payload.messages) ||
    payload.messages.length < 1 ||
    payload.messages.length > 16 ||
    ![null, undefined, "page", "post", "course", "training", "job"].includes(
      payload.kind,
    )
  )
    throw new Error("invalid_payload");
  const messages = payload.messages.map((m) => {
    if (
      !m ||
      !["user", "assistant"].includes(m.role) ||
      typeof m.content !== "string" ||
      !m.content.trim() ||
      m.content.length > 6000
    )
      throw new Error("invalid_message");
    return { role: m.role, content: m.content };
  });
  if (
    messages.at(-1).role !== "user" ||
    messages.at(-1).content.length > 1500 ||
    messages.reduce((n, m) => n + m.content.length, 0) > 24000
  )
    throw new Error("invalid_history");
  let listing = null;
  if (payload.listing !== undefined && payload.listing !== null) {
    const value = payload.listing;
    if (
      value.kind !== "job" ||
      !Number.isInteger(value.offset) ||
      value.offset < 0 ||
      value.offset > 10000 ||
      (value.snapshot_id !== undefined &&
        !/^[a-f0-9]{64}$/.test(value.snapshot_id))
    )
      throw new Error("invalid_listing");
    listing = {
      kind: "job",
      offset: value.offset,
      ...(value.snapshot_id ? { snapshot_id: value.snapshot_id } : {}),
    };
  }
  return { messages, kind: payload.kind || null, listing };
}
async function readPayload(request) {
  if (!request.headers.get("content-type")?.includes("application/json"))
    return { error: json({ error: "Expected JSON" }, 415) };
  if (Number(request.headers.get("content-length") || 0) > 32768)
    return { error: json({ error: "Το μήνυμα είναι πολύ μεγάλο." }, 413) };
  const reader = request.body?.getReader();
  if (!reader) return { error: json({ error: "Missing body" }, 400) };
  let size = 0,
    content = "";
  const decoder = new TextDecoder();
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      size += part.value.length;
      if (size > 32768) {
        await reader.cancel();
        return { error: json({ error: "Το μήνυμα είναι πολύ μεγάλο." }, 413) };
      }
      content += decoder.decode(part.value, { stream: true });
    }
    content += decoder.decode();
    try {
      return { payload: validate(JSON.parse(content)) };
    } catch {
      return { error: json({ error: "Μη έγκυρη ερώτηση ή ιστορικό." }, 422) };
    }
  } finally {
    reader.releaseLock();
  }
}
function limit(value, fallback, ceiling) {
  return /^\d+$/.test(value || "") && Number(value) > 0
    ? Math.min(Number(value), ceiling)
    : fallback;
}
export function createCloudHandler({
  env = process.env,
  fetcher = fetch,
  getStore = () => createStore(database(env)),
} = {}) {
  return async (request) => {
    const route = new URL(request.url).pathname.split("/").pop();
    const method =
      route === "chat" ? "POST" : route === "status" ? "GET" : null;
    if (!method) return json({ error: "Not found" }, 404);
    if (request.method !== method)
      return json({ error: "Method not allowed" }, 405);
    if (route === "status") {
      try {
        const snapshot = await getStore().snapshot();
        return json({
          ready: !!env.OPENAI_API_KEY,
          answer_mode: "openai",
          model: env.OPENAI_MODEL || "gpt-6-luna",
          snapshot_id: snapshot.id,
          documents: snapshot.documents,
          chunks: snapshot.chunks,
          backend: "vercel-postgres",
        });
      } catch {
        return json(
          {
            ready: false,
            answer_mode: "openai",
            backend: "vercel-postgres",
            error: "Η βάση αναζήτησης δεν είναι ακόμη διαθέσιμη.",
          },
          503,
        );
      }
    }
    const origin = request.headers.get("origin");
    if (origin && origin !== new URL(request.url).origin)
      return json({ error: "Origin not allowed" }, 403);
    const parsed = await readPayload(request);
    if (parsed.error) return parsed.error;
    if (!env.OPENAI_API_KEY)
      return json(
        { error: "Η υπηρεσία απαντήσεων δεν έχει συνδεθεί ακόμη." },
        503,
      );
    let store, snapshot;
    try {
      store = getStore();
      snapshot = await store.snapshot(
        parsed.payload.listing?.snapshot_id || null,
      );
      const ip = (
        request.headers.get("x-vercel-forwarded-for") ||
        request.headers.get("x-forwarded-for") ||
        "unknown"
      )
        .split(",")[0]
        .trim()
        .slice(0, 100);
      const clientHash = createHmac(
        "sha256",
        env.RAG_RATE_LIMIT_SALT || env.OPENAI_API_KEY,
      )
        .update(ip)
        .digest("hex");
      if (
        !(await store.reserve(
          clientHash,
          limit(env.RAG_DAILY_LIMIT, 100, 10000),
          limit(env.RAG_HOURLY_IP_LIMIT, 20, 1000),
        ))
      )
        return json(
          { error: "Το demo έφτασε το όριο αιτημάτων. Δοκίμασε αργότερα." },
          429,
        );
    } catch {
      return json(
        { error: "Η βάση αναζήτησης δεν είναι διαθέσιμη. Δοκίμασε ξανά." },
        503,
      );
    }
    const abort = new AbortController();
    const signal = AbortSignal.any([
      request.signal,
      abort.signal,
      AbortSignal.timeout(90000),
    ]);
    let cancelled = false;
    const encoder = new TextEncoder();
    const body = new ReadableStream({
      async start(controller) {
        const emit = (event, data) => {
          if (!cancelled)
            controller.enqueue(
              encoder.encode(
                `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`,
              ),
            );
        };
        try {
          emit("stage", { stage: "searching" });
          const start = performance.now();
          const question = parsed.payload.messages.at(-1).content;
          const listing =
            parsed.payload.listing || jobListIntent(parsed.payload.messages);
          if (listing) {
            const result = await store.listJobs(snapshot, listing.offset);
            signal.throwIfAborted();
            emit("sources", {
              sources: result.sources,
              retrieval_ms: Math.round(performance.now() - start),
            });
            emit("delta", { text: jobListAnswer(result, question) });
            emit("done", {
              mode: "job-list",
              usage: null,
              next_listing: result.next,
            });
            return;
          }
          if (isCatalogueCount(question)) {
            const summary = await store.catalogueCount(snapshot);
            signal.throwIfAborted();
            emit("sources", {
              sources: summary ? [summary.source] : [],
              retrieval_ms: Math.round(performance.now() - start),
            });
            emit("delta", { text: catalogueAnswer(summary, question) });
            emit("done", { mode: "catalogue", usage: null });
            return;
          }
          const query = expandQuery(contextualQuery(parsed.payload.messages));
          const vector = await embed(
            query,
            env.OPENAI_API_KEY,
            signal,
            fetcher,
          );
          signal.throwIfAborted();
          const sources = await store.search(
            snapshot,
            query,
            vector,
            parsed.payload.kind,
          );
          signal.throwIfAborted();
          emit("sources", {
            sources,
            retrieval_ms: Math.round(performance.now() - start),
          });
          if (!sources.length) {
            emit("delta", {
              text: "Δεν βρήκα σχετική πηγή στο site. Δοκίμασε μια πιο συγκεκριμένη ερώτηση.",
            });
            emit("done", { mode: "openai", usage: null });
          } else {
            emit("stage", { stage: "answering" });
            for await (const [event, data] of answer(
              parsed.payload,
              sources,
              env,
              signal,
              fetcher,
            ))
              emit(event, data);
          }
        } catch (error) {
          if (!cancelled && !request.signal.aborted)
            emit("error", {
              code:
                error instanceof ProviderError && error.status === 429
                  ? "billing_or_rate_limit"
                  : "answer_unavailable",
              message:
                error instanceof ProviderError && error.status === 429
                  ? "Έλεγξε το διαθέσιμο API balance ή δοκίμασε σε λίγο."
                  : "Δεν ολοκληρώθηκε η απάντηση. Δοκίμασε ξανά.",
            });
        } finally {
          if (!cancelled) controller.close();
        }
      },
      cancel() {
        cancelled = true;
        abort.abort();
      },
    });
    return new Response(body, {
      headers: {
        ...HEADERS,
        "Content-Type": "text/event-stream; charset=utf-8",
        "X-Accel-Buffering": "no",
      },
    });
  };
}
