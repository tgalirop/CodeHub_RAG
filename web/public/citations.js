/** Sources actually cited in the visible answer, preserving their original IDs. */
export function citedSources(text, sources = []) {
  const ids = new Set();
  let fenced = false;
  for (const line of text.split("\n")) {
    if (line.startsWith("```")) {
      fenced = !fenced;
      continue;
    }
    if (fenced) continue;
    const prose = line.replace(/`[^`]*(?:`|$)/g, "");
    for (const match of prose.matchAll(/\[(\d+)\]/g)) ids.add(Number(match[1]));
  }
  const available = new Map(
    (Array.isArray(sources) ? sources : [])
      .filter((source) => source && Number.isInteger(source.id))
      .map((source) => [source.id, source]),
  );
  return [...ids]
    .filter((id) => available.has(id))
    .map((id) => available.get(id));
}
