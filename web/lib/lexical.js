import config from "./search-config.json" with { type: "json" };

export const SEARCH_CONFIG = config;
const stopwords = new Set(config.stopwords);
export function tokens(text) {
  const normalized = text
    .toLowerCase()
    .replaceAll("ς", "σ")
    .replaceAll("ß", "ss")
    .normalize("NFKD")
    .replace(/\p{M}/gu, "");
  return (
    normalized.match(
      /(?:\.[\p{L}][\p{L}\p{N}_]*|[\p{L}\p{N}]+(?:[.+#][\p{L}\p{N}]+|[+#]+)*)/gu,
    ) || []
  ).filter((term) => !stopwords.has(term));
}
export function expandQuery(query) {
  const original = tokens(query);
  const aliases = config.concepts.flatMap(([roots, words]) =>
    original.some((term) => roots.some((root) => term.startsWith(root)))
      ? words
          .split(" ")
          .filter((word) => !original.includes(word.toLowerCase()))
      : [],
  );
  return query + (aliases.length ? "\n" + [...new Set(aliases)].join(" ") : "");
}
export function contextualQuery(messages) {
  const current = messages.at(-1).content.trim();
  if (
    current.length < 160 &&
    /^(?:και(?:\s|$)|κι(?:\s|$)|αυτ|εκεί|εκει|πόσο|ποσο|πότε|ποτε|τι γίνεται|what about|how about|and\b|it\b|that\b)/iu.test(
      current,
    )
  ) {
    const previous = messages
      .slice(0, -1)
      .findLast((message) => message.role === "user");
    if (previous) return previous.content.slice(0, 400) + "\n" + current;
  }
  return current;
}
export function fuse(rankings) {
  const scores = new Map();
  for (const ranking of rankings) {
    const seen = new Set();
    ranking.forEach((id, i) => {
      if (!seen.has(id))
        scores.set(id, (scores.get(id) || 0) + 1 / (60 + i + 1));
      seen.add(id);
    });
  }
  return [...scores]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([id]) => id);
}
export function diverseChunks(dense, lexical, limit = 5) {
  const metadata = new Map([...dense, ...lexical].map((row) => [row.id, row]));
  const pageRanks = [dense, lexical].map((rows) => [
    ...new Set(rows.map((row) => row.url)),
  ]);
  const chunkRanks = fuse([
    dense.map((row) => row.id),
    lexical.map((row) => row.id),
  ]);
  return fuse(pageRanks)
    .slice(0, limit)
    .map((url) =>
      metadata.get(chunkRanks.find((id) => metadata.get(id).url === url)),
    );
}
