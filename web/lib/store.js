import postgres from "postgres";
import { SEARCH_CONFIG, tokens, diverseChunks, fuse } from "./lexical.js";

let cached;
export function database(env = process.env) {
  const url = env.CLOUD_DATABASE_URL || env.SUPABASE_DATABASE_URL;
  if (!url) throw new Error("cloud_not_configured");
  if (cached?.url === url) return cached.sql;
  const parsed = new URL(url);
  const local =
    ["localhost", "127.0.0.1"].includes(parsed.hostname) && env.VERCEL !== "1";
  // Never carry sslmode=disable from a pasted connection string into production.
  parsed.searchParams.delete("sslmode");
  const sql = postgres(parsed.toString(), {
    ssl: local ? false : "require",
    prepare: false,
    max: 1,
    idle_timeout: 20,
    connect_timeout: 10,
    max_lifetime: 60 * 5,
    onnotice: () => {},
  });
  cached = { url, sql };
  return sql;
}

export function createStore(sql) {
  const transaction = (operation) =>
    sql.begin(async (tx) => {
      await tx`SET LOCAL statement_timeout = '8000ms'`;
      await tx`SET LOCAL search_path = rag_cloud, extensions, public, pg_catalog`;
      return operation(tx);
    });
  return {
    snapshot: (snapshotId = null) =>
      transaction(async (tx) => {
        const [row] =
          await tx`SELECT id,config,documents,chunks FROM rag_cloud.snapshots WHERE ready
            AND ((${snapshotId}::text IS NULL AND active) OR id=${snapshotId})`;
        if (!row) throw new Error("cloud_index_missing");
        const c = row.config;
        if (
          c.model !== "text-embedding-3-small" ||
          c.dimensions !== 384 ||
          c.tokenizer_version !== SEARCH_CONFIG.tokenizer_version ||
          c.query_version !== SEARCH_CONFIG.query_version ||
          c.lexical_config_hash !== SEARCH_CONFIG.fingerprint ||
          c.format !== "cloud-v1"
        ) {
          throw new Error("cloud_index_incompatible");
        }
        return row;
      }),
    reserve: (clientHash, daily, hourly) =>
      transaction(async (tx) => {
        const [row] =
          await tx`SELECT rag_cloud.reserve_request(${clientHash},${daily},${hourly}) AS allowed`;
        return row.allowed;
      }),
    catalogueCount: (snapshot, collection = "course") =>
      transaction(async (tx) => {
        if (!["course", "job"].includes(collection))
          throw new Error("invalid_collection");
        const catalogueUrl =
          collection === "course"
            ? "https://codehub.gr/training-programs/"
            : "https://codehub.gr/open-job-opportunities/";
        const [count] = await tx`SELECT count(DISTINCT url)::integer AS total
        FROM rag_cloud.chunks WHERE snapshot_id=${snapshot.id} AND ${collection}=ANY(categories)`;
        const rows =
          await tx`SELECT url,title,body AS text,heading_path,categories,warnings,fetched_at
        FROM rag_cloud.chunks WHERE snapshot_id=${snapshot.id}
        AND url=${catalogueUrl} ORDER BY id`;
        const pattern =
          collection === "course"
            ? /\b(\d+)\s+courses?\b/gi
            : /\b(\d+)\s+open\s+roles?\b/gi;
        const matches = rows.flatMap((row) =>
          [...row.text.matchAll(pattern)].map((match) => ({
            total: Number(match[1]),
            row,
          })),
        );
        const totals = new Set(matches.map((match) => match.total));
        if (totals.size !== 1) return null;
        const { total, row } = matches[0];
        // The published catalogue is authoritative if indexed page coverage differs.
        return {
          total,
          indexed_courses: count.total,
          indexed_entries: count.total,
          source: { ...row, id: 1 },
        };
      }),
    listCatalogue: (snapshot, collection, requestedOffset = 0) =>
      transaction(async (tx) => {
        if (!["course", "job"].includes(collection))
          throw new Error("invalid_collection");
        const [count] = await tx`SELECT count(DISTINCT url)::integer AS total
        FROM rag_cloud.chunks WHERE snapshot_id=${snapshot.id} AND ${collection}=ANY(categories)`;
        const offset = Math.min(
          requestedOffset,
          Math.max(0, Math.floor((count.total - 1) / 10) * 10),
        );
        const rows = await tx`WITH jobs AS (
        SELECT DISTINCT ON(url) url,title,body AS text,heading_path,categories,warnings,fetched_at
        FROM rag_cloud.chunks WHERE snapshot_id=${snapshot.id} AND ${collection}=ANY(categories)
        ORDER BY url,length(body) DESC,id)
        SELECT * FROM jobs ORDER BY lower(title),url LIMIT 10 OFFSET ${offset}`;
        return {
          total: count.total,
          offset,
          sources: rows.map((row, index) => ({ ...row, id: index + 1 })),
          next:
            offset + rows.length < count.total
              ? {
                  kind: collection,
                  offset: offset + rows.length,
                  snapshot_id: snapshot.id,
                }
              : null,
        };
      }),
    search: (snapshot, query, vector, kind = null, options = {}) =>
      transaction(async (tx) => {
        const literal = JSON.stringify(vector);
        const terms = [...new Set(tokens(query))];
        const dense =
          await tx`SELECT id,url,categories,1-(embedding <=> ${literal}::vector) AS score
        FROM rag_cloud.chunks WHERE snapshot_id=${snapshot.id}
        AND (${kind}::text IS NULL OR ${kind}=ANY(categories))
        ORDER BY embedding <=> ${literal}::vector,id LIMIT 100`;
        const lexical = terms.length
          ? await tx`SELECT c.id,c.url,c.categories,sum(p.weight) AS score
        FROM rag_cloud.postings p JOIN rag_cloud.chunks c
          ON c.snapshot_id=p.snapshot_id AND c.id=p.chunk_id
        WHERE p.snapshot_id=${snapshot.id} AND p.term=ANY(${terms}::text[])
        AND (${kind}::text IS NULL OR ${kind}=ANY(c.categories))
        GROUP BY c.id,c.url,c.categories ORDER BY score DESC,c.id LIMIT 100`
          : [];
        if (snapshot.config.parent_documents) {
          const pageRanks = [dense, lexical].map((rows) => [
            ...new Set(rows.map((r) => r.url)),
          ]);
          if (options.preferredKind) {
            for (const rows of [dense, lexical])
              pageRanks.push([
                ...new Set(
                  rows
                    .filter((r) => r.categories.includes(options.preferredKind))
                    .map((r) => r.url),
                ),
              ]);
          }
          const urls = fuse(pageRanks).slice(
            options.offset || 0,
            (options.offset || 0) + 12,
          );
          // A small verified contact page enables useful next steps for missing
          // course fees/dates. It is still subject to the relevance/evidence check.
          if (!kind && !urls.includes("https://codehub.gr/contact/"))
            urls.push("https://codehub.gr/contact/");
          if (!urls.length) return [];
          const pages =
            await tx`SELECT url,title,body AS text,categories,warnings,fetched_at
            FROM rag_cloud.pages WHERE snapshot_id=${snapshot.id} AND url=ANY(${urls}::text[])`;
          const byUrl = new Map(pages.map((p) => [p.url, p]));
          return urls
            .filter((url) => byUrl.has(url))
            .map((url, index) => ({
              ...byUrl.get(url),
              id: index + 1,
              heading_path: [],
              truncated: byUrl.get(url).text.length > 16000,
              text: byUrl.get(url).text.slice(0, 16000),
            }));
        }
        const selected = diverseChunks(dense, lexical);
        if (!selected.length) return [];
        const rows =
          await tx`SELECT id,url,title,body AS text,heading_path,categories,warnings,fetched_at
        FROM rag_cloud.chunks WHERE snapshot_id=${snapshot.id}
        AND id=ANY(${selected.map((row) => row.id)}::text[])`;
        const byId = new Map(rows.map((row) => [row.id, row]));
        return selected.map((row, i) => ({ ...byId.get(row.id), id: i + 1 }));
      }),
  };
}
