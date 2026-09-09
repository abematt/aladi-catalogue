# Adding a language to the catalogue

How to add a third catalogue (French, German, …) alongside English and Italian.
Written after adding Italian on 2026-09-09, which is the worked example
throughout.

The app is deliberately built so that **adding a language is a data job, not a
coding job**: one entry in `langs.py`, then three script runs. If you find
yourself adding a per-language branch to `server.py` or `app/index.html`, stop
— that's a sign the registry needs the information instead.

---

## The one idea to hold onto

There are two unrelated "languages" in every OPAC URL, and conflating them
will waste your afternoon:

| In a URL | What it is | Varies? |
|---|---|---|
| `search~S171*eng`, `record=b123~S171*eng` | The **site's interface** language — which language the OPAC's own buttons and labels are in | **No.** Stays `eng` for every catalogue, including record permalinks for Italian books. |
| `&l=ita` | The **item's** language — what the book/CD is actually in | **Yes.** This is the catalogue. |

That's the whole mechanism. Everything below is bookkeeping around it.

---

## Step 1 — Pick the code, and check the size first

The OPAC's own dropdown is the list of valid codes (MARC three-letter codes).
As of 2026-09-09 it offers 32:

```
ara ast baq cat chi cze dan dut eng fin fre glg ger grc gre heb hin hun
ita jpn lat nor oci pol por rum rus slo spa swe ukr urd
```

Re-read it from the search form rather than trusting this list:

```bash
curl -s -A "Mozilla/5.0 (compatible; personal-catalogue-sync; non-commercial)" \
  "https://aladi.diba.cat/search~S171*eng/X" \
  | grep -o '<option value="[a-z]\{3\}"[^>]*>[^<]*'
```

**Size it before you commit.** One request tells you what you're in for — write
a broad query of that language's commonest stopwords and read the count:

```python
import scraper, re
q = "et+or+de+or+la+or+le+or+les+or+un+or+une+or+des+or+du+or+pour"   # French
body = scraper.get(f"{scraper.BASE}/search~S171*eng/X?SEARCH={q}&l=fre&m=a&SORT=AX")
print(re.search(r"(\d+) results found", body).group(1))
```

Measured 2026-09-09 (books only, so total items run higher):

| Code | Language | Books | Verdict |
|---|---|---|---|
| `eng` | English | 28,621 | in the catalogue |
| `fre` | French | 22,144 | fine, but see the cap warning |
| `ger` | German | 4,243 | easy |
| `ita` | Italian | 5,283 | in the catalogue |
| `por` | Portuguese | 1,897 | easy |
| `spa` | Spanish | ~31,400+ | **problem** — see below |
| `cat` | Catalan | 32,000 (capped) | **don't** — see below |

### Two languages you can't just add

**Catalan is at the cap.** The OPAC refuses to report more than 32,000 results,
and Catalan returns exactly `32000` for even a single common word — meaning the
true total is unknown and larger. The broad-query-plus-residuals approach
assumes the main query returns a *countable* set it can page through; at the cap
you have no idea what you're missing. Catalan would need a different strategy
entirely (slicing by year or material before querying).

**Spanish is big enough to break the server.** A very common word 502s outright:

```
spa "de"            -> HTTP 502 Bad Gateway
spa "para"          -> 31,448 results
spa "microbiologia" -> 119 results
```

So a 502 is not always a transient blip — for a large language it's the OPAC
giving up on the result set. If a broad query 502s repeatedly while narrower
ones succeed, the query is too broad, not the server unwell. Retrying harder
won't help and isn't polite; narrow the query instead.

The useful rule: **if the broad query returns 32,000, or 502s, the language
needs a different approach and is not a drop-in addition.** Say so rather than
scraping something incomplete.

---

## Step 2 — Add the registry entry

Everything language-specific lives in [`langs.py`](../langs.py):

```python
"fre": {
    "code": "fre",
    "label": "French",           # English name — page copy, "French-language items"
    "native": "français",        # what the header switch shows
    "main_q": "et+or+de+or+la+or+le+or+les+or+un+or+une+or+des+or+du+or+pour",
    "residual_terms": ["au", "aux", "ce", "qui", "que", "sur", "avec", ...],
},
```

- **`main_q`** — the broad boolean query, `+or+` separated and URL-encoded. Aim
  for the commonest stopwords, enough to catch nearly everything in one search.
  Verify it against the OPAC before moving on (Step 1's snippet).
- **`residual_terms`** — follow-up `term AND NOT (main)` sweeps that catch
  records containing none of the main words. English needs ~42 of them because
  it runs close to the result cap; Italian's 36 returned single-digit extras,
  which is the signal the main query already reached almost everything. **Fewer
  is fine for a small language.** Each term is one extra search per material
  type, so 36 terms × 9 types ≈ 320 searches on top of the page fetches.

Nothing else needs editing. The server exposes the new language through
`/api/languages`, and the UI renders another segment in the header switch from
that. The sign-in page picks up its name from the registry too.

---

## Step 3 — Run the three scripts

Locally, or on the box for production (see Step 5):

```bash
python3 scraper.py --lang=fre      # -> data/fre/snapshots/<date>.json + .csv
python3 diff.py    --lang=fre      # no-op until there are two snapshots
python3 enrich.py  --lang=fre      # -> data/fre/enrichment.jsonl (needs yaz-client)
```

Or in one pass: `ALADI_LANGS=fre ./run_weekly.sh`

Timing, from the Italian run: ~7,700 items took about 8 minutes to scrape at the
default 4 workers, and ~3 minutes to enrich at ~40 records/second. Scale from
there; English is roughly ten times the work.

Both scraping and enrichment are **resumable and idempotent**. A killed scrape
resumes with `--resume`; enrichment skips bibs it already has, so just run it
again to fill gaps.

### Then check it actually worked

```bash
# composition — does the mix look plausible for that language?
python3 -c "
import json, collections
d = json.load(open('data/fre/snapshots/<date>.json'))
print(d['count'], collections.Counter(r[6] or 'a' for r in d['items']))"

# are the records really in that language? read a few titles
python3 -c "
import json
for r in json.load(open('data/fre/snapshots/<date>.json'))['items'][:5]:
    print(r[0][:70], '|', r[1][:30])"
```

Eyeballing five titles catches a wrong `l=` code immediately, which no amount of
counting will.

---

## Step 4 — Check the genres, and expect to fix a rule

Genre buckets are derived from the **Catalan** subject headings the catalogue
attaches to every record, so they work for any item language with no changes.
That's why Italian needed almost no genre work. Only two things are
language-specific:

- The **tech** rules, which also match the title, so thin-subject books still
  classify.
- The **history** fallback, which reads the title for non-fiction whose subjects
  are sparse.

Add your language's stems to those, then check coverage:

```bash
python3 enrich.py --lang=fre --rederive     # recompute locally, no network
python3 -c "
import json, collections
c = collections.Counter()
for l in open('data/fre/enrichment.jsonl'):
    for g in json.loads(l).get('genres', []): c[g] += 1
print(c.most_common(15))"
```

### The trap that cost the most time

Genre keys are **substring matches on diacritic-folded text**. Folding strips
accents, so two different words can collapse onto one stem and a rule that
looks obviously correct can mis-tag hundreds of records.

Two real cases from the Italian addition:

| Key | Also matched | Damage | Fix |
|---|---|---|---|
| `illustrator` (Adobe) | "illustrators", Italian "illustratore" | 38 books *about* illustrators filed as creative software | Space-pad: `" illustrator "` |
| `italia` (the language) | "Itàlia" the **country** — both fold to `italia` | 704 Italian pop-music CDs tagged language-learning | Padding can't help; both forms can end a heading. Use **position** instead |

That second one is the general lesson. When folding destroys the distinction,
look for a structural signal. Here the catalogue writes a language as the
heading and a country as a subdivision:

```
Italià —  Gramàtica            <- the language, leads the heading
Música popular —  Itàlia       <- the country, always a subdivision
```

So `is_language_subject()` in `enrich.py` tests the head of the heading rather
than searching the whole string.

**Always diff the genre counts before and after a rule change, across every
language** — a plausible-looking rule moved 704 records:

```bash
cp data/eng/enrichment.jsonl /tmp/eng-before.jsonl
# ...edit the rule...
python3 enrich.py --rederive && python3 enrich.py --lang=fre --rederive
python3 - <<'EOF'
import json
a = {r["bib"]: set(r.get("genres",[])) for r in map(json.loads, open("/tmp/eng-before.jsonl"))}
b = {r["bib"]: set(r.get("genres",[])) for r in map(json.loads, open("data/eng/enrichment.jsonl"))}
rem, add = {}, {}
for k in a:
    for g in a[k] - b.get(k, set()): rem[g] = rem.get(g, 0) + 1
    for g in b.get(k, set()) - a[k]: add[g] = add.get(g, 0) + 1
print("removed:", rem); print("added  :", add)
EOF
```

Then read a handful of the records that changed and decide whether the change is
right. Both Italian fixes looked like regressions by count alone and were
improvements once the titles were read.

---

## Step 5 — Deploy

The production box is `root@<box>`, serving
https://<private host>. Full operational detail is in the README's
"Running in production"; what matters for a new language:

**The box's `data/` is the source of truth and is never synced from the Mac.**
`deploy/push.sh` excludes it deliberately. So a new language must be **scraped
on the box** — don't rsync your local copy up.

```bash
# 1. code first (langs.py must be there before any run can use it)
deploy/push.sh root@<box>

#    If a sandbox blocks the script, its two steps run fine by hand:
#      rsync -az --delete --exclude .git --exclude .vscode --exclude '__pycache__' \
#        --exclude data --exclude logs --exclude .env --exclude nohup.out \
#        --exclude .DS_Store ./ root@<box>:/srv/aladi/
#      ssh root@<box> 'cd /srv/aladi && \
#        docker compose -f deploy/compose.yaml up -d --build'

# 2. seed the new language ON THE BOX (a full scrape; minutes, not seconds)
ssh root@<box> 'cd /srv/aladi && \
  docker compose -f deploy/compose.yaml run --rm -e ALADI_LANGS=fre jobs'

# 3. confirm the app sees it
ssh root@<box> 'docker exec aladi-web-1 python -c "
import server
for l in server.languages_payload(): print(l)"'
```

The Sunday 07:30 cron needs **no change** — it runs the same `jobs` service,
which loops over `ALADI_LANGS` (default `eng ita`; add the new code to the
default in `run_weekly.sh` and `deploy/compose.yaml`).

Until the language has a snapshot, `/api/languages` reports it
`ready: false`, the UI shows it dimmed and disabled with a "Not synced yet"
tooltip, and `/api/catalogue?lang=<code>` returns a 404 naming the command to
run. So a half-finished addition degrades gracefully rather than erroring —
verified by registering a language with no data and loading the app.

That's also the cheapest way to confirm the registry really is the only
edit: add the entry, load the page, and the new segment appears in the
header switch with no other change.

**If you change the data layout** (not just add a language), the box needs the
matching `mv` **before** the new code goes up, or the app finds no snapshots.
That's what the one-time migration in the README's production section did.

---

## Where each concern lives

| Concern | File | Note |
|---|---|---|
| Which catalogues exist, their queries | `langs.py` | The only file you must edit |
| `--lang=` / `$ALADI_LANG` resolution, `data/<lang>/` paths | `langs.py` | `resolve()`, `data_dir()` |
| Scraping | `scraper.py` | `l=` from the registry; `SCOPE` stays `S171*eng` |
| Genre/audience derivation | `enrich.py` | Catalan subjects — language-neutral; title fallbacks aren't |
| Per-language API | `server.py` | `?lang=` on catalogue/enrichment/snapshots/diffs; unknown code → 400 |
| Language-independent API | `server.py` | `/api/libraries`, `/api/availability` — branch codes and copy status don't vary |
| Header switch, page copy | `app/index.html` | Driven by `/api/languages`; no hardcoded list |
| Weekly pass | `run_weekly.sh` | Loops `$ALADI_LANGS` |

### Two UI details that will bite if you touch the loading path

Both were bugs during the Italian work:

1. **Guard in-flight fetches.** A `loadSeq` counter drops a response that
   arrives for a language the user has already left; without it a slow English
   payload lands on top of the Italian view.
2. **Per-catalogue filters must reset on switch.** Genre and audience are
   cleared in `switchLang()`. A genre present in both catalogues (Crime, say)
   would otherwise keep filtering while its chip renders unpressed, because
   `buildGenreChips()` only clears a selection the new catalogue *lacks*. The
   library picker and type filter are deliberately kept — a branch holds both
   languages, and "Books" means the same thing everywhere. The diff tab's
   load-once cache also has to be invalidated.

---

## Politeness — non-negotiable, and it applies per language

From CLAUDE.md, and adding a language does not buy you extra budget:

- `aladi.diba.cat/robots.txt` disallows `/search` and `/record=`. This is a
  personal, weekly-cadence tool; **never host a public mirror.**
- **4 workers** (`ALADI_WORKERS`), not more.
- One full sync a week, per language. Don't re-scrape a language repeatedly to
  test — a snapshot is already on disk, and `--rederive` recomputes genres with
  **no network at all**. Use it.
- Availability lookups stay on-demand, one per click.
- Z39.50 (`enrich.py`) is the sanctioned machine interface and is the preferred
  path for per-record data. Its result sets cap at 500, so it enriches
  per-record; it can't enumerate the catalogue.

A full English run is ~2,500 requests and has drawn zero blocks in months.
The Italian run measured **1,024** (333 searches + 691 page fetches), so the
weekly pass is now ~3,500. Keep it in that order of magnitude.

Rough sizing for a new language: `searches = (1 + residual_terms) × materials`
(exact — 37 × 9 = 333 for Italian), and `page fetches ≳ total_items / 12`
(638 predicted vs 691 actual; the residual sweeps re-fetch a few pages, and
the scrape dedupes by bib afterwards). Worth computing before you run it — it
tells you both the load and the wall-clock time.

---

## Checklist

```
[ ] Code is in the OPAC's dropdown
[ ] Broad query verified against the OPAC — returns a real count, not 32,000, not a 502
[ ] Registry entry added to langs.py (code, label, native, main_q, residual_terms)
[ ] scraper.py --lang=<code> completed; snapshot count and material mix look plausible
[ ] Read five titles — they really are in that language
[ ] enrich.py --lang=<code> completed; genre distribution sane
[ ] Language stems added to the tech/history title fallbacks if needed
[ ] Genre counts diffed before/after any rule change, for EVERY language
[ ] Added to ALADI_LANGS defaults (run_weekly.sh, deploy/compose.yaml)
[ ] README language table + CLAUDE.md updated with the measured count
[ ] Code pushed to the box, then the language scraped ON the box
[ ] /api/languages shows it ready; header switch offers it; a search returns rows
```
