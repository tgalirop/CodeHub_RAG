import { tokens } from "./lexical.js";

const JOB =
  /^(?:jobs?|careers?|roles?|positions?|vacancies|openings?|καριερ\p{L}*|θεσε\p{L}*|δουλει\p{L}*|αγγελι\p{L}*|ευκαιρι\p{L}*)$/u;
const FILLER = new Set(
  `ποιεσ ποιοι ποια τι ειναι υπαρχουν εχει εχετε προσφερει προσφερετε
  διαθετει διαθετετε διαθεσιμεσ διαθεσιμα επαγγελματικεσ εργασιασ εργασία ανοιχτεσ
  δειξε δειξτε πες πειτε ολεσ ολα λιστα καταλογοσ καταλογο καποιεσ αλλεσ
  what which list show tell me all any available open opportunities work employment
  does do there have has offer offers codehub code.hub code hub παρακαλω please
  τις της τους στις`
    .split(/\s+/)
    .flatMap(tokens),
);
const NEXT =
  /^(?:next|more|others?|continue|αλλεσ|αλλα|επομεν\p{L}*|περισσοτερ\p{L}*|συνεχ\p{L}*)$/u;

export function jobListIntent(messages) {
  const question = messages.at(-1).content;
  const words = tokens(question);
  const next = words.some((word) => NEXT.test(word));
  const hasJob = words.some((word) => JOB.test(word));
  const allowed = words.every(
    (word) => JOB.test(word) || NEXT.test(word) || FILLER.has(word),
  );
  if (!allowed) return null;
  if (next) {
    const previous = messages
      .slice(0, -1)
      .findLast((message) => message.role === "assistant");
    const page = previous?.content
      .replaceAll("**", "")
      .match(/(?:Θέσεις|Roles)\s+(\d+)[–-](\d+)\s+(?:από|of)\s+(\d+)/iu);
    if (page && Number(page[2]) < Number(page[3]))
      return { kind: "job", offset: Number(page[2]) };
  }
  const asksList = words.some((word) =>
    /^(?:ποιεσ|ποιοι|ποια|τι|δειξε|δειξτε|πες|πειτε|what|which|list|show|available|open|ολεσ)$/u.test(
      word,
    ),
  );
  const nominal = words.every(
    (word) =>
      JOB.test(word) ||
      /^(?:εργασιασ|work|employment|opportunities)$/u.test(word),
  );
  return hasJob && (asksList || nominal) ? { kind: "job", offset: 0 } : null;
}

export function jobListAnswer(result, question) {
  const greek = /[\u0370-\u03ff]/u.test(question);
  if (!result.sources.length)
    return greek
      ? "Δεν βρήκα αγγελίες στα διαθέσιμα στοιχεία. Δες τον κατάλογο Open Job Opportunities στο codehub.gr."
      : "I couldn't find job listings in the available data. Please check Open Job Opportunities on codehub.gr.";
  const first = result.offset + 1,
    last = result.offset + result.sources.length;
  const intro = greek
    ? `Από τις αγγελίες για τις οποίες έχω διαθέσιμα στοιχεία:\n\n**Θέσεις ${first}–${last} από ${result.total}**:`
    : `From the job listings I have information about:\n\n**Roles ${first}–${last} of ${result.total}**:`;
  const rows = result.sources.map((source) => {
    const title = source.title.replace(/\s*\|\s*Code\.Hub.*$/i, "");
    const reference = source.url.match(/\/po-(\d+)-/i)?.[1];
    return `- **${title}**${reference ? ` (PO-${reference})` : ""}. [${source.id}]`;
  });
  const footer = greek
    ? "Για την τρέχουσα διαθεσιμότητα, τις προϋποθέσεις και την αίτηση, άνοιξε την αντίστοιχη αγγελία."
    : "Open each listing for current availability, requirements and applications.";
  return [intro, rows.join("\n"), footer].join("\n\n");
}
