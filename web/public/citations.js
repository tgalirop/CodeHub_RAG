// Visit prose citations once, leaving inline/fenced code unchanged.
function mapCitations(text, replace) {
  let fenced = false;
  return text
    .split("\n")
    .map((line) => {
      if (line.startsWith("```")) {
        fenced = !fenced;
        return line;
      }
      if (fenced) return line;
      return line.replace(/`[^`]*(?:`|$)|\[(\d+)\]/g, (match, id) =>
        id === undefined ? match : replace(Number(id), match),
      );
    })
    .join("\n");
}

/** Sources actually cited in the answer, retaining the API's evidence IDs. */
export function citedSources(text, sources = []) {
  const ids = new Set();
  mapCitations(text, (id, match) => {
    ids.add(id);
    return match;
  });
  const available = new Map(
    (Array.isArray(sources) ? sources : [])
      .filter((source) => source && Number.isInteger(source.id))
      .map((source) => [source.id, source]),
  );
  return [...ids]
    .filter((id) => available.has(id))
    .map((id) => available.get(id));
}

/** Display consecutive labels in first-mention order without mutating raw evidence. */
export function numberedCitations(text, sources = []) {
  const used = citedSources(text, sources);
  const labels = new Map(used.map((source, index) => [source.id, index + 1]));
  return {
    text: mapCitations(text, (id, match) =>
      labels.has(id) ? `[${labels.get(id)}]` : match,
    ),
    sources: used.map((source, index) => ({ ...source, id: index + 1 })),
  };
}
