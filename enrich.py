#!/usr/bin/env python3
"""Enrich book records with genre/audience data from Aladi's Z39.50 server.

For each book bib id in the latest snapshot, fetches the full MARC record
(via yaz-client, batched — Z39.50 is the catalog's machine interface) and
derives:
  - form:     MARC 008/33 literary form (fiction / nonfiction / poetry / drama …)
  - audience: MARC 008/22 target audience (kids / teen / adult)
  - genres:   buckets mapped from Catalan subject headings (650/655) + form

Appends to data/enrichment.jsonl (resumable — already-done bibs are skipped),
so it can run as a background trickle and the app picks up coverage as it grows.

Usage:  python3 enrich.py [--limit N] [--batch N] [--workers N]
"""
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata

ROOT = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(ROOT, "data", "snapshots")
ENRICH_JSONL = os.path.join(ROOT, "data", "enrichment.jsonl")
HOST = "aladi.diba.cat:210/INNOPAC"
BATCH = 250
WORKERS = 3
LOCK = threading.Lock()

# --- genre buckets: substring match on diacritic-folded Catalan subject headings ---
# Keys match inside " <folded subject> " — a leading/trailing space in a key
# means a word boundary. Stems avoid Catalan plural spelling shifts (c -> qu).
GENRE_RULES = [
    ("Crime", ["polici", "novel·la negra", "novel·les negres", "detectiv"]),
    ("Thriller", ["intriga", "suspens", "thriller", "espionatge"]),
    ("Adventure", ["aventur"]),
    ("Fantasy", ["fantasti", "fantasia", "fades", "dracs"]),
    ("Sci-fi", ["ciencia-ficcio", "ciencia ficcio"]),
    ("Romance", ["romant", "amorosa", "amoroses"]),
    ("Historical", ["historic"]),
    ("Horror", ["terror", "horror", " por "]),
    ("War", ["guerra", "bel·li"]),
    ("Western", [" oest ", "western"]),
    ("Humor", ["humor"]),
    ("Erotica", ["eroti"]),
    ("Comics", ["comic", "historieta", "novel·la grafica", "novel·les grafiques", "manga"]),
    ("Short stories", ["contes"]),
    ("Poetry", ["poesia", "poemes"]),
    ("Drama", ["teatre"]),
    ("Biography", ["biografi", "autobiografi", "memories"]),
    ("History", ["historia"]),
    ("Travel", ["viatge", "guies turisti", "descripcions"]),
    ("Cooking", ["cuina", "gastronomia", "receptes", "alimentacio"]),
    ("Art & Design", [" art ", " arts ", "pintura", "fotografia", "arquitectura", "disseny", "moda"]),
    ("Music", ["musica", "musics", "cantants", "opera", " rock "]),
    ("Science & Nature", ["ciencia", "ciencies", "natura", "animals", "plantes", "univers",
                          "fisica", "biologia", "matemat", "medi ambient", "evolucio"]),
    ("Language & Learning", ["angles", "llengua", "vocabulari", "diccionari", "gramatica",
                             "ensenyament", "aprenentatge", "lectura"]),
    ("Self-help & Psychology", ["autoajuda", "psicologia", "creixement personal", "felicitat",
                                "meditacio", "mindfulness"]),
    ("Business & Economics", ["economia", "empres", "negocis", "marqueting", "finances",
                              "lideratge", "treball"]),
    ("Philosophy & Religion", ["filosofia", "religio", "espiritualitat", "budisme", "biblia",
                               "islam", "etica"]),
    ("Politics & Society", ["politica", "societat", "sociologia", "feminisme", "globalitzacio"]),
    ("Sports", ["esport", "futbol", "basquet", "ciclisme", "muntanyisme", "ioga"]),
    ("Health", ["salut", "medicina", "malalt", "nutricio"]),
    ("Computers & Tech", ["informatica", "internet", "programacio", "intel·ligencia artificial",
                          "videojocs", "tecnologia"]),
]
# Tech sub-genres: matched against subjects AND the (English) title, so books
# whose Catalan subjects are thin still classify. Additive to GENRE_RULES.
TECH_RULES = [
    ("Tech: Data & AI", ["machine learning", "deep learning", "neural network",
                         "artificial intelligence", "intel·ligencia artificial",
                         "aprenentatge automatic", "data science", "data analy", "big data",
                         "mineria de dades", "estadistica matematica"]),
    ("Tech: Programming", [" python ", "javascript", " java ", " c++ ", " sql ", "programming",
                           "programaci", " coding ", "algorithm", "algorism", "software",
                           "llenguatges de programacio", "bases de dades", "database"]),
    ("Tech: Games & Web Dev", ["unreal", "unity", "videojocs", "jocs per ordinador",
                               "game develop", "web develop", " html ", " css "]),
    ("Tech: IT & Security", [" linux ", " unix ", "hacking", "cybersec", "ciberseguretat",
                             "seguretat informatica", "criptograf", "cryptograph", " devops ",
                             "kubernetes", "internet de les coses", "xarxes d'ordinadors",
                             "computer network"]),
    ("Tech: Creative software", ["photoshop", "lightroom", "indesign", "illustrator",
                                 "premiere", "autocad", "blender", "onshape",
                                 "programa d'ordinador", "disseny assistit"]),
    ("Tech: Maker & Hardware", ["raspberry", "arduino", "robotic", "electronic"]),
]
FICTION_FORMS = set("1fj")           # novels, general fiction, short stories
FORM_GENRE = {"p": "Poetry", "d": "Drama", "h": "Humor", "j": "Short stories"}
KID_AUD = set("abcj")


def fold(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower())
                   if unicodedata.category(c) != "Mn")


def latest_snapshot():
    snaps = sorted(f for f in os.listdir(SNAP_DIR) if f.endswith(".json"))
    with open(os.path.join(SNAP_DIR, snaps[-1])) as f:
        return json.load(f)


def derive_genres(form, subjects, title, bio):
    folded = [" " + fold(s) + " " for s in subjects]
    tfolded = " " + fold(title) + " "
    genres = set()
    for name, keys in GENRE_RULES:
        if any(k in s for s in folded for k in keys):
            genres.add(name)
    for name, keys in TECH_RULES:
        if any(k in s for s in folded + [tfolded] for k in keys):
            genres.add(name)
            genres.add("Computers & Tech")
    if form in FORM_GENRE:
        genres.add(FORM_GENRE[form])
    if form in FICTION_FORMS or form in FORM_GENRE or ("novel·l" in " ".join(folded)):
        genres.add("Fiction")
    elif form == "0":
        genres.add("Non-fiction")
    if bio:
        genres.add("Biography")
    return sorted(genres)


def derive(fields008, subjects, form_extra, title=""):
    form = fields008[33] if len(fields008) > 33 else " "
    aud = fields008[22] if len(fields008) > 22 else " "
    bio = fields008[34:35] in ("a", "b", "c", "d")
    return {"form": form.strip(), "aud": aud.strip(),
            "genres": derive_genres(form, subjects, title, bio),
            "subjects": subjects, **form_extra}


def run_batch(bibs):
    """One yaz-client session: find+show per bib, in order; parse transcript."""
    cmds = [f"open {HOST}"]
    for b in bibs:
        cmds += [f"find @attr 1=12 {b}", "show 1"]
    cmds.append("quit")
    try:
        out = subprocess.run(["yaz-client"], input="\n".join(cmds) + "\n",
                             capture_output=True, text=True, timeout=600).stdout
    except subprocess.TimeoutExpired:
        return []
    # split transcript into per-find segments, in command order
    segs = re.split(r"Sent searchRequest\.", out)[1:]
    results = []
    for bib, seg in zip(bibs, segs):
        hm = re.search(r"Number of hits: (\d+)", seg)
        if not hm or hm.group(1) == "0":
            results.append({"bib": bib, "miss": True})
            continue
        f008 = re.search(r"^008 (.*)$", seg, re.M)
        subjects = [re.sub(r"\s*\$\w", " — ", s).strip(" .—")
                    for s in re.findall(r"^6[05][05].{0,4}\$a (.*)$", seg, re.M)]
        pages = re.search(r"^300\s+\$a\s*([^$]*)", seg, re.M)
        # sanity: response must belong to the requested bib
        idm = re.search(r"\$a \.?(b\d{7,8})", seg)
        if idm and not idm.group(1).startswith(bib):
            results.append({"bib": bib, "miss": True})
            continue
        extra = {"phys": pages.group(1).strip(" :;.")} if pages else {}
        results.append({"bib": bib, **derive(f008.group(1) if f008 else "", subjects, extra,
                                             title=TITLES.get(bib, ""))})
    return results


TITLES = {}


def rederive():
    """Recompute genres for every enriched record from stored subjects + form —
    no network. Run after changing GENRE_RULES/TECH_RULES."""
    tmp = ENRICH_JSONL + ".tmp"
    n = 0
    with open(ENRICH_JSONL) as fin, open(tmp, "w") as fout:
        for line in fin:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if not r.get("miss"):
                r["genres"] = derive_genres(r.get("form", ""), r.get("subjects", []),
                                            TITLES.get(r["bib"], ""),
                                            "Biography" in r.get("genres", []))
                n += 1
            fout.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, ENRICH_JSONL)
    print(f"rederived genres for {n} records")


def main():
    args = dict(a.split("=") for a in sys.argv[1:] if "=" in a)
    limit = int(args.get("--limit", 0))
    batch = int(args.get("--batch", BATCH))
    workers = int(args.get("--workers", WORKERS))

    snap = latest_snapshot()
    for r in snap["items"]:
        TITLES[r[5]] = r[0]
    if "--rederive" in sys.argv:
        rederive()
        return
    done = set()
    if os.path.exists(ENRICH_JSONL):
        with open(ENRICH_JSONL) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["bib"])
                except Exception:
                    pass
    books = [r[5] for r in snap["items"] if (r[6] if len(r) > 6 else "a") == "a"]
    todo = [b for b in books if b not in done]
    if limit:
        todo = todo[:limit]
    print(f"books={len(books)} done={len(done)} todo={len(todo)} "
          f"(batch={batch}, workers={workers})", flush=True)
    if not todo:
        print("nothing to do")
        return
    batches = [todo[i:i + batch] for i in range(0, len(todo), batch)]
    t0 = time.time()
    n = 0
    with open(ENRICH_JSONL, "a") as fh:
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            for res in ex.map(run_batch, batches):
                with LOCK:
                    for r in res:
                        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    fh.flush()
                n += len(res)
                rate = n / (time.time() - t0)
                print(f"{n}/{len(todo)} enriched ({rate:.0f}/s, "
                      f"~{(len(todo)-n)/max(rate,0.1)/60:.0f} min left)", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
