"""Small, auditable bilingual domain glossary; original query terms are retained."""

from .lexical import tokens

QUERY_VERSION = "el-en-domain-v1"
CONCEPTS = (
    (
        ("εκπαιδευ", "καταρτισ", "σεμιναρ", "μαθημ", "μαθω"),
        "training education learning upskilling",
    ),
    (("ομαδ", "εργαζομεν", "προσωπικ"), "team employees workforce"),
    (("μισθοδοσ",), "payroll payment"),
    (("εργασιακ", "συμμορφωσ"), "employment compliance contracts"),
    (("επικοινων", "τηλεφων"), "contact email phone"),
    (("προσλαβ", "προσληψ", "στελεχω"), "recruitment hiring"),
    (("διευθυντ", "ηγετικ"), "executive leadership"),
    (("δουλεια", "σταδιοδρομ", "καριερ"), "job career opportunities"),
    (("πιστοποι",), "certification certificate"),
    (("δεδομεν",), "data"),
    (("τεχνητ", "νοημοσυν"), "artificial intelligence AI"),
    (("μεντορ", "καθοδηγησ"), "mentoring coaching"),
)


def expand_query(query: str) -> tuple[str, list[str]]:
    original = tokens(query)
    aliases = []
    for roots, words in CONCEPTS:
        if any(term.startswith(roots) for term in original):
            aliases.extend(word for word in words.split() if word.casefold() not in original)
    aliases = list(dict.fromkeys(aliases))
    return query + ("\n" + " ".join(aliases) if aliases else ""), aliases
