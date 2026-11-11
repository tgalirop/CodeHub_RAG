export function catalogueAnswer(
  summary,
  question,
  collection = "course",
  language = null,
) {
  const greek = language
    ? language === "el"
    : /[\u0370-\u03ff]/u.test(question);
  if (!summary)
    return greek
      ? "Δεν μπορώ να επιβεβαιώσω τον συνολικό αριθμό από τον διαθέσιμο κατάλογο."
      : "I couldn't verify the total count in the available catalogue.";
  if (collection === "job")
    return greek
      ? `Με βάση τα διαθέσιμα στοιχεία του καταλόγου **Open Job Opportunities**, αναφέρονται **${summary.total} ρόλοι**. [1]`
      : `The available **Open Job Opportunities** catalogue records **${summary.total} roles**. [1]`;
  return greek
    ? `Στον κατάλογο **Training Programs** αναφέρονται **${summary.total} courses/εκπαιδευτικά προγράμματα**. [1]`
    : `The **Training Programs** catalogue lists **${summary.total} courses/training programmes**. [1]`;
}

export function catalogueListAnswer(result, collection, language) {
  const greek = language === "el",
    jobs = collection === "job";
  if (!result.sources.length)
    return greek
      ? "Δεν βρήκα καταχωρήσεις σε αυτόν τον κατάλογο στα διαθέσιμα στοιχεία."
      : "I couldn't find entries in this catalogue in the available data.";
  const first = result.offset + 1,
    last = result.offset + result.sources.length;
  const label = greek
    ? jobs
      ? "Θέσεις"
      : "Μαθήματα"
    : jobs
      ? "Roles"
      : "Courses";
  const intro = greek
    ? `Από τον κατάλογο για τον οποίο έχω διαθέσιμα στοιχεία:\n\n**${label} ${first}–${last} από ${result.total}**:`
    : `From the catalogue I have information about:\n\n**${label} ${first}–${last} of ${result.total}**:`;
  const rows = result.sources.map((source) => {
    const title = source.title.replace(/\s*\|\s*Code\.Hub.*$/i, "");
    const reference = jobs ? source.url.match(/\/po-(\d+)-/i)?.[1] : null;
    return `- **${title}**${reference ? ` (PO-${reference})` : ""}. [${source.id}]`;
  });
  const footer = greek
    ? jobs
      ? "Άνοιξε κάθε αγγελία για την τρέχουσα διαθεσιμότητα, τις προϋποθέσεις και την αίτηση."
      : "Άνοιξε τη σελίδα κάθε μαθήματος για το περιεχόμενο και τις προϋποθέσεις του."
    : jobs
      ? "Open each listing for current availability, requirements and applications."
      : "Open each course page for its content and prerequisites.";
  return [intro, rows.join("\n"), footer].join("\n\n");
}
