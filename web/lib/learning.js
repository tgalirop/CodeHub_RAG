// Published course facts, not model-generated profile scores or inferred skills.
export function courseFacts(source) {
  const text = source.text || "";
  const hours = text.match(/^Duration:\s*(\d+(?:\.\d+)?)\s*Hours?\s*$/im);
  const level = text.match(/^Difficulty Level:\s*([^\n]+)$/im);
  const audience = text.match(/^Audience:\s*([^\n]+)$/im);
  const section = text
    .split(/\n\n/)
    .find((block) => /(?:^|> )Prerequisite Knowledge\n/i.test(block));
  const prerequisites = section
    ? section.slice(section.indexOf("\n") + 1).trim()
    : null;
  const groups = prerequisites?.split(/\nBeneficial but not mandatory\n/i);
  return {
    url: source.url,
    title: source.title,
    hours: hours && Number(hours[1]) > 0 ? Number(hours[1]) : null,
    level: level?.[1].trim() || null,
    audience: audience?.[1].trim() || null,
    prerequisites: prerequisites?.slice(0, 2400) || null,
    required_prerequisites: groups?.length === 2 ? groups[0].trim() : null,
    beneficial_prerequisites: groups?.length === 2 ? groups[1].trim() : null,
    fetched_at: source.fetched_at || null,
    evidence: [hours?.[0], level?.[0], audience?.[0]]
      .filter(Boolean)
      .join("\n"),
  };
}

export function learningRequest(payload) {
  let advisor = null,
    explore = null;
  if (payload.advisor != null) {
    const p = payload.advisor;
    if (
      typeof p.goal !== "string" ||
      !p.goal.trim() ||
      p.goal.length > 500 ||
      typeof p.background !== "string" ||
      p.background.length > 500 ||
      ![null, 8, 16, 24, 40, 80].includes(p.max_hours)
    )
      throw new Error("invalid_advisor");
    advisor = {
      goal: p.goal.trim(),
      background: p.background.trim(),
      max_hours: p.max_hours,
    };
  }
  if (payload.explore != null) {
    const p = payload.explore;
    if (
      !["compare", "details"].includes(p.type) ||
      !Array.isArray(p.urls) ||
      p.urls.length !== (p.type === "compare" ? 2 : 1) ||
      new Set(p.urls).size !== p.urls.length ||
      !p.urls.every(
        (url) =>
          typeof url === "string" &&
          /^https:\/\/codehub\.gr\/course\/[a-z0-9-]+\/$/.test(url),
      ) ||
      !/^[a-f0-9]{64}$/.test(p.snapshot_id)
    )
      throw new Error("invalid_course_selection");
    explore = { type: p.type, urls: p.urls, snapshot_id: p.snapshot_id };
  }
  if (payload.listing && explore) throw new Error("conflicting_actions");
  return { advisor, explore };
}

export function eligibleCourses(pages, maxHours) {
  return pages.filter((p) => {
    const hours = courseFacts(p).hours;
    return maxHours == null || (hours != null && hours <= maxHours);
  });
}

export const LEARNING_INSTRUCTIONS = `When a visitor profile is supplied, use only the
skills the visitor actually declared. Unknown skills are unknown, not deficiencies.
Recommend up to three courses with a concrete reason, relevant prerequisites and
what still needs clarification. A learning sequence is your suggestion, never an
official Code.Hub pathway or a guarantee of employment. Never invent match scores.
If the goal or background is too vague to make useful recommendations, ask one
focused clarification instead of guessing. max_hours is a ceiling on each course's
published total duration, NOT weeks or weekly study time; never recommend a course
above it. For a course comparison cover BOTH selected courses: duration, scope,
prerequisites and fit for the declared goal. Attribute every factual claim to its
source. Do not invent price, start date, eligibility or registration availability.
Published course facts are deterministic extracts; missing fields stay unknown.
required_prerequisites and beneficial_prerequisites preserve explicit source grouping.
Do not call the required group optional or the beneficial group mandatory.`;
