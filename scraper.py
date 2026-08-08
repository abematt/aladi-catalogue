#!/usr/bin/env python3
"""Weekly catalogue sync: all English-language books in the Aladi OPAC
(aladi.diba.cat — Barcelona province municipal libraries network).

The OPAC (classic Innovative Millennium) has no "list everything" endpoint and
caps keyword results at 32,000, so coverage comes from one broad boolean query
(~28.6k records) plus residual "term AND NOT (main)" sweeps. Records are
deduplicated by bib id and written as a dated snapshot.

Usage:
    python3 scraper.py            # full run -> data/snapshots/YYYY-MM-DD.json + .csv
    python3 scraper.py --resume   # keep page cache from an interrupted run

Politeness: 4 workers by default (~6-8 req/s), honest UA, retries with backoff.
A full run is ~2,500 requests. Note aladi.diba.cat's robots.txt disallows
/search for robots (anti-indexing); keep this to personal, low-volume use.
"""
import concurrent.futures as cf
import csv
import datetime
import html as htmllib
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request

BASE = "https://aladi.diba.cat"
SCOPE = "S171*eng"
MAIN_Q = "and+or+the+or+a+or+in+or+de+or+of"
RESIDUAL_TERMS = [
    "s", "i", "la", "el", "en", "es", "on", "for", "is", "by", "my", "un",
    "le", "y", "o", "no", "new", "love", "art", "con", "per", "del", "que",
    "com", "els", "al", "der", "die", "das", "1", "2", "3", "you", "we",
    "how", "what", "who", "story", "book", "life", "world", "little",
]
WORKERS = int(os.environ.get("ALADI_WORKERS", "4"))
ROOT = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(ROOT, "data", "snapshots")
PAGES_JSONL = os.path.join(ROOT, "data", "pages_cache.jsonl")
LOCK = threading.Lock()
UA = {"User-Agent": "Mozilla/5.0 (compatible; personal-catalogue-sync; non-commercial)"}


def get(url, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            if attempt == tries - 1:
                print(f"FAIL {url[:120]} : {e}", flush=True)
                return None
            time.sleep(2.0 * (attempt + 1))


def search_page1(query):
    """Run a fresh keyword search; return (total, browse_url_template)."""
    url = f"{BASE}/search~{SCOPE}/X?SEARCH={query}&l=eng&m=a&SORT=AX"
    body = get(url)
    if body is None:
        return None, None
    if "No matches found" in body or "NO ENTRIES FOUND" in body.upper():
        return 0, None
    m = re.search(r"(\d+) results found", body)
    total = int(m.group(1)) if m else None
    hm = re.search(r'href="(/search~[^"]*%2CB/browse)"', body)
    template = None
    if hm:
        raw = urllib.parse.unquote(hm.group(1)).split("#")[0]
        template = re.sub(r"/\d+,(\d+),(\d+),B/browse$", r"/{start},\1,\2,B/browse", raw)
    return total, (BASE + template) if template else None


ROW_SPLIT = re.compile(r'<td class="briefCitRow">')
BIB_RE = re.compile(r'name="save"\s+value="(b\d+)"')
TITLE_RE = re.compile(r'<span class="titular">\s*<a href="[^"]*">(.*?)</a>', re.S)
ISBN_RE = re.compile(r"isbn=(\d{9,13}[Xx]?)&")
YEAR_RE = re.compile(r"\b(1[4-9]\d\d|20[0-3]\d)\b")


TITULAR_SPAN_RE = re.compile(r'<span class="titular">.*?</a>\s*</span>', re.S)
RATING_CUT_RE = re.compile(r'<span\s+id="rating_txt".*$', re.S)
ENDS_WITH_YEAR_RE = re.compile(r"(?<![-\d])(1[4-9]\d\d|20[0-3]\d)\]?\.?\s*$")


def parse_rows(body):
    rows = []
    for ch in ROW_SPLIT.split(body)[1:]:
        bib = BIB_RE.search(ch)
        title = TITLE_RE.search(ch)
        if not bib or not title:
            continue
        t = htmllib.unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip()
        isbn = ISBN_RE.search(ch)
        seg = ch.split('<div class="descript">', 1)[-1]
        seg = RATING_CUT_RE.sub("", seg)
        seg = TITULAR_SPAN_RE.sub("", seg)
        seg = re.sub(r"<!--.*?-->", "", seg, flags=re.S)
        seg = re.sub(r"<[^>]+>", "\n", seg)
        lines = [htmllib.unescape(l).strip() for l in seg.split("\n")]
        lines = [l for l in lines if l and l not in ("+ info", t)]
        # Template order is fixed: optional author line, then imprint line.
        author, pub = "", ""
        colon_idx = next((i for i, l in enumerate(lines) if " : " in l), None)
        if colon_idx is not None:
            pub = lines[colon_idx]
            if colon_idx > 0:
                author = lines[0]
        elif len(lines) >= 2:
            author, pub = lines[0], lines[1]
        elif len(lines) == 1:
            # Lone line: an imprint ends with a bare year ("London, 2020");
            # an author's lifespan year is preceded by a dash ("..., 1940-2017").
            if ENDS_WITH_YEAR_RE.search(lines[0]):
                pub = lines[0]
            else:
                author = lines[0]
        ym = YEAR_RE.findall(pub)
        rows.append({
            "bib": bib.group(1),
            "title": t,
            "author": author.rstrip(" ,."),
            "pub": pub.rstrip(" ,.").strip(),
            "year": ym[-1] if ym else "",
            "isbn": isbn.group(1) if isbn else "",
        })
    return rows


def load_done():
    done = set()
    if os.path.exists(PAGES_JSONL):
        with open(PAGES_JSONL) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["key"])
                except Exception:
                    pass
    return done


def fetch_and_store(key, url, fh):
    body = get(url)
    if body is None:
        return
    rows = parse_rows(body)
    with LOCK:
        fh.write(json.dumps({"key": key, "rows": rows}) + "\n")
        fh.flush()


def scrape_query(tag, query, done, fh):
    total, template = search_page1(query)
    if not total or not template:
        print(f"[{tag}] total={total} (skip)", flush=True)
        return
    starts = range(1, total + 1, 12)
    todo = [(f"{tag}:{s}", template.format(start=s)) for s in starts if f"{tag}:{s}" not in done]
    print(f"[{tag}] total={total}, pages todo: {len(todo)}", flush=True)
    n = 0
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for _ in cf.as_completed([ex.submit(fetch_and_store, k, u, fh) for k, u in todo]):
            n += 1
            if n % 200 == 0:
                print(f"[{tag}] {n}/{len(todo)} pages", flush=True)


def main():
    resume = "--resume" in sys.argv
    if not resume and os.path.exists(PAGES_JSONL):
        os.remove(PAGES_JSONL)
    done = load_done()
    with open(PAGES_JSONL, "a") as fh:
        scrape_query("main", MAIN_Q, done, fh)
        for t in RESIDUAL_TERMS:
            scrape_query(f"res-{t}", f"{t}+and+not+%28{MAIN_Q}%29", done, fh)

    seen = {}
    with open(PAGES_JSONL) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            for r in rec["rows"]:
                seen.setdefault(r["bib"], r)
    items = sorted(seen.values(), key=lambda r: (r["title"].casefold(), r["bib"]))
    today = datetime.date.today().isoformat()
    os.makedirs(SNAP_DIR, exist_ok=True)
    snap_path = os.path.join(SNAP_DIR, f"{today}.json")
    with open(snap_path, "w") as f:
        json.dump({"date": today, "count": len(items),
                   "items": [[r["title"], r["author"], r["pub"], r["year"], r["isbn"], r["bib"]] for r in items]},
                  f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(SNAP_DIR, f"{today}.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["title", "author", "publisher", "year", "isbn", "record_id", "permalink"])
        for r in items:
            w.writerow([r["title"], r["author"], r["pub"], r["year"], r["isbn"], r["bib"],
                        f"{BASE}/record={r['bib']}~{SCOPE}"])
    os.remove(PAGES_JSONL)
    print(f"DONE: {len(items)} unique records -> {snap_path}", flush=True)


if __name__ == "__main__":
    main()
