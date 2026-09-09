#!/usr/bin/env python3
"""Language registry — the one place that knows which catalogues exist.

The catalogue is per item-language: the OPAC's `l=` query parameter limits a
search to items *in* that language (the `S171*eng` in every URL is only the
site's own interface language, and stays `eng` throughout).

Each language gets its own state directory under data/<lang>/, so snapshots,
enrichment and diffs never mix:

    data/eng/snapshots/  data/eng/enrichment.jsonl  data/eng/diffs/
    data/ita/snapshots/  data/ita/enrichment.jsonl  data/ita/diffs/

`main_q` is the broad boolean query that pulls the bulk of the catalogue in one
search — the most common stopwords in that language. `residual_terms` are the
follow-up "term AND NOT (main)" sweeps that pick up whatever the main query
missed. English needs many of them (28.6k records against a 32k result cap);
Italian is small enough (~5k books) that a short list suffices.
"""

LANGS = {
    "eng": {
        "code": "eng",
        "label": "English",
        "native": "english",
        "main_q": "and+or+the+or+a+or+in+or+de+or+of",
        "residual_terms": [
            "s", "i", "la", "el", "en", "es", "on", "for", "is", "by", "my", "un",
            "le", "y", "o", "no", "new", "love", "art", "con", "per", "del", "que",
            "com", "els", "al", "der", "die", "das", "1", "2", "3", "you", "we",
            "how", "what", "who", "story", "book", "life", "world", "little",
        ],
    },
    "ita": {
        "code": "ita",
        "label": "Italian",
        "native": "italiano",
        "main_q": "e+or+di+or+la+or+il+or+che+or+un+or+una+or+del+or+della+or+per+or+non+or+a+or+in",
        "residual_terms": [
            "i", "gli", "le", "lo", "dei", "delle", "nel", "nella", "con", "su",
            "da", "al", "alla", "come", "piu", "anche", "ma", "se", "sono",
            "storia", "vita", "amore", "mondo", "libro", "uomo", "donna", "casa",
            "1", "2", "3", "the", "and", "of", "el", "en", "y",
        ],
    },
}

DEFAULT_LANG = "eng"


def resolve(argv=None, env=None):
    """Pick the language from `--lang=xx` in argv, else $ALADI_LANG, else eng."""
    import os
    import sys

    argv = sys.argv[1:] if argv is None else argv
    for arg in argv:
        if arg.startswith("--lang="):
            code = arg.split("=", 1)[1].strip().lower()
            if code not in LANGS:
                raise SystemExit(f"unknown --lang={code}; known: {', '.join(LANGS)}")
            return LANGS[code]
    code = (env if env is not None else os.environ).get("ALADI_LANG", DEFAULT_LANG).strip().lower()
    if code not in LANGS:
        raise SystemExit(f"unknown ALADI_LANG={code}; known: {', '.join(LANGS)}")
    return LANGS[code]


def data_dir(root, lang):
    import os

    return os.path.join(root, "data", lang["code"] if isinstance(lang, dict) else lang)
