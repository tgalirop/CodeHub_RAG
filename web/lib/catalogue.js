import { tokens } from "./lexical.js";

const FILLER = new Set(
  `ποσα ποσες ποσοι συνολο συνολικα συνολικοσ συνολικη αριθμοσ
  υπαρχουν υπαρχει εχει εχετε προσφερει προσφερετε διαθετει διαθετετε διαθεσιμα
  καταλογοσ καταλογο καταλογου ιστοσελιδα σελιδα codehub code.hub code hub
  what how many total number count does do there have has offer offers available offered
  listed catalog catalogue all overall exist exists website site programs programmes
  ειναι εχουν μαθηματα εκπαιδευτικα προγραμματα προγραμματων εκπαιδευσησ`.split(
    /\s+/,
  ),
);
const COURSE_TERM =
  /^(?:trainings?|courses?|μαθημ\p{L}*|εκπαιδευ\p{L}*|σεμιναρ\p{L}*)$/u;

/** Only unfiltered whole-catalogue totals: subject/status/date qualifiers fall through. */
export function isCatalogueCount(question) {
  const words = tokens(question);
  const normalized = words.join(" ");
  const asksCount =
    /(?:^| )(?:ποσα|ποσες|ποσοι|συνολο|αριθμοσ)(?: |$)|\bhow many\b|\b(?:total|number|count)\b/u.test(
      normalized,
    );
  return (
    asksCount &&
    words.some((word) => COURSE_TERM.test(word)) &&
    words.every((word) => COURSE_TERM.test(word) || FILLER.has(word))
  );
}

export function catalogueAnswer(summary, question) {
  const greek = /[\u0370-\u03ff]/u.test(question);
  if (!summary)
    return greek
      ? "Δεν μπορώ να επιβεβαιώσω τον συνολικό αριθμό μαθημάτων από τον αποθηκευμένο κατάλογο. Δες τον κατάλογο Training Programs στο codehub.gr."
      : "I couldn't verify the total course count in the saved catalogue. Please check Training Programs on codehub.gr.";
  return greek
    ? `Στον κατάλογο **Training Programs** αναφέρονται **${summary.total} courses/εκπαιδευτικά προγράμματα**. [1]`
    : `The **Training Programs** catalogue lists **${summary.total} courses/training programmes**. [1]`;
}
