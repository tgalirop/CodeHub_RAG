import { createCloudHandler } from "../lib/cloud.js";

/** Direct serverless RAG with PostgreSQL, or the original container relay. */
export default {
  async fetch(request) {
    if (process.env.CLOUD_DATABASE_URL || process.env.SUPABASE_DATABASE_URL)
      return createCloudHandler()(request);
    const route = new URL(request.url).pathname.split("/").pop();
    const allowed =
      route === "chat" ? "POST" : route === "status" ? "GET" : null;
    if (!allowed) return Response.json({ error: "Not found" }, { status: 404 });
    if (request.method !== allowed) {
      return Response.json(
        { error: "Method not allowed" },
        { status: 405, headers: { Allow: allowed } },
      );
    }
    const base = process.env.RAG_API_URL;
    const token = process.env.RAG_API_TOKEN;
    if (!base || !token) {
      return Response.json(
        { error: "Η υπηρεσία δεν έχει συνδεθεί ακόμη." },
        { status: 503 },
      );
    }
    try {
      const origin = new URL(base);
      const local =
        ["127.0.0.1", "localhost"].includes(origin.hostname) &&
        process.env.VERCEL !== "1";
      if (
        origin.username ||
        origin.password ||
        !(
          origin.protocol === "https:" ||
          (local && origin.protocol === "http:")
        )
      ) {
        throw new Error("Invalid upstream configuration");
      }
      let body;
      if (allowed === "POST") {
        if (
          !request.headers.get("content-type")?.includes("application/json")
        ) {
          return Response.json({ error: "Expected JSON" }, { status: 415 });
        }
        if (Number(request.headers.get("content-length") || 0) > 32768) {
          return Response.json(
            { error: "Το μήνυμα είναι πολύ μεγάλο." },
            { status: 413 },
          );
        }
        body = await request.text();
        if (new TextEncoder().encode(body).length > 32768) {
          return Response.json(
            { error: "Το μήνυμα είναι πολύ μεγάλο." },
            { status: 413 },
          );
        }
        try {
          JSON.parse(body);
        } catch {
          return Response.json({ error: "Invalid JSON" }, { status: 400 });
        }
      }
      const response = await fetch(new URL("/api/" + route, origin), {
        method: allowed,
        body,
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + token,
        },
        signal: AbortSignal.any([request.signal, AbortSignal.timeout(90000)]),
        redirect: "error",
      });
      if (!response.ok) {
        return Response.json(
          { error: "Η υπηρεσία δεν είναι διαθέσιμη. Δοκίμασε ξανά." },
          {
            status:
              response.status === 429
                ? 429
                : response.status === 422
                  ? 422
                  : 502,
          },
        );
      }
      return new Response(response.body, {
        status: 200,
        headers: {
          "Content-Type":
            route === "chat"
              ? "text/event-stream; charset=utf-8"
              : "application/json; charset=utf-8",
          "Cache-Control": "no-store, no-transform",
          "X-Content-Type-Options": "nosniff",
        },
      });
    } catch (error) {
      return Response.json(
        {
          error:
            error.name === "TimeoutError"
              ? "Η απάντηση καθυστέρησε. Δοκίμασε ξανά."
              : "Δεν ήταν δυνατή η σύνδεση με την υπηρεσία.",
        },
        { status: 502 },
      );
    }
  },
};
