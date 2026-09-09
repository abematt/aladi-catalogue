# Aladí Catalogue

A local, browsable catalogue of **every item in a given language** in the Aladi
OPAC (aladi.diba.cat — the Barcelona province municipal libraries network) —
books, music CDs, vinyl, DVDs, printed scores, board games, magazines, maps,
video games — with weekly snapshots, week-over-week diffs, and **on-demand live
availability** (which copies are on the shelf vs checked out, per library).

Two catalogues today, switchable from the wordmark in the app's header:

| Language | Code | Scale |
|---|---|---|
| English | `eng` | ~64.5k items |
| Italian | `ita` | ~6.8k items |

Built because the OPAC has no "browse everything in one language" view — its
language filter only applies on top of a keyword search.

## Use it

```bash
python3 server.py        # then open http://localhost:8377
```

- **Catalogue tab** — instant search over title/author/publisher (diacritic-
  insensitive), year range, sorting, CSV export of whatever's filtered.
- Click any book — fetches its record page **live** and shows every copy across
  the network: library, call number, and status (`Available`, `DUE 14-08-26` =
  checked out with due date, `In Transit`, …). Nothing is bulk-polled; one
  request per click, cached 5 min.
- **Weekly changes tab** — what entered/left the catalogue between snapshots.

## Data pipeline

| Piece | Job |
|---|---|
| `langs.py` | The language registry — which catalogues exist, and each one's broad query + residual sweeps. Add a language here. |
| `scraper.py` | Full sync → `data/<lang>/snapshots/YYYY-MM-DD.json` + `.csv`. English is ~2,500 requests, ~45 min at the default 4 workers; Italian is roughly a tenth of that. Resumable (`--resume`). |
| `diff.py` | Compares the two newest snapshots → `data/<lang>/diffs/<from>__<to>.json`. |
| `enrich.py` | Per-record MARC data over Z39.50 → `data/<lang>/enrichment.jsonl`. |
| `server.py` | Serves the app + `/api/catalogue`, `/api/enrichment`, `/api/snapshots`, `/api/diffs` (all taking `?lang=`), plus `/api/languages`, `/api/libraries` and `/api/availability?bib=…`. |
| `run_weekly.sh` | scraper + diff + enrich, once per language, logged to `logs/`. |

Every script defaults to English and takes `--lang=<code>`:

```bash
python3 scraper.py --lang=ita     # Italian full sync
python3 diff.py --lang=ita
python3 enrich.py --lang=ita
ALADI_LANGS=ita ./run_weekly.sh   # weekly pass for one language only
```

State is per language under `data/<lang>/` (`snapshots/`, `diffs/`,
`enrichment.jsonl`), so the catalogues never mix. `data/libraries.json` is
shared — branch codes are language-independent, and so is the app's "my
libraries" selection.

### Adding another language

The OPAC's own language list is the menu (`ita`, `lat`, `oci`, … as `l=` codes).
Add an entry to `langs.py` with a `main_q` of that language's commonest
stopwords plus a `residual_terms` list, then run the three scripts with the new
`--lang=`. Nothing else needs touching: the server picks the language up from
`/api/languages` and the app renders a new segment in the header switch.

### How the scrape covers "everything"

The OPAC (classic Innovative Millennium) requires a keyword and caps results at
32,000, so each language gets one broad boolean query of its commonest
stopwords (English: `and OR the OR a OR in OR de OR of`, ≈28.6k books; Italian:
`e OR di OR la OR il OR che OR un …`, ≈5.3k books) plus residual sweeps
(`term AND NOT (main)`) to catch records containing none of the main words.
Deduped by bib record id. Coverage is near-total but not provably complete — a
record whose indexed text contains none of the probe words would be missed. On
Italian the residual sweeps return single-digit extras, which is the sign the
main query already reached nearly everything.

Note the `S171*eng` in every OPAC URL is the site's own **interface** language
and stays `eng` for all catalogues; the *item* language is the `l=` parameter.

## Weekly schedule

`com.abraham.aladi-weekly.plist` runs `run_weekly.sh` every **Sunday 07:30**
(if the Mac is asleep, it fires on next wake).

```bash
# install / reinstall
cp com.abraham.aladi-weekly.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.abraham.aladi-weekly.plist
# remove
launchctl unload ~/Library/LaunchAgents/com.abraham.aladi-weekly.plist
rm ~/Library/LaunchAgents/com.abraham.aladi-weekly.plist
```

## Politeness / terms

- `aladi.diba.cat/robots.txt` disallows `/search` and `/record=` for robots; the
  file's stated purpose is to stop search engines *indexing* those pages. A
  personal weekly sync isn't indexing, but respect the spirit: **keep workers at
  4, keep the weekly cadence, don't share a hosted mirror.** Availability
  lookups are one request per click.
- No bot checks observed: no captcha/WAF; ~5k requests with zero blocks. The
  main risk is server-side throttling if concurrency is raised — don't.
- If this ever needs to be more than personal, ask Diba for an export, or check
  their Z39.50 service (the standard protocol for programmatic catalog queries).

## Running in production

Live at **https://<private host>** (since 2026-09-09) on the Hetzner box
shared with the ledger and drive apps (`~/ledger/docs/server-handoff.md` describes the
box). Stack: `deploy/compose.yaml` behind the box's shared Caddy, which owns TLS.
Sign-in is in the app: two accounts, 30-day session cookie, lockout after six bad
attempts. Google is told not to index it, and the OPAC's politeness rules still apply
(one scrape a week, availability lookups only on click).

| Task | How |
|---|---|
| Deploy a code change | `deploy/push.sh root@<box>` (rsyncs code, rebuilds, restarts; never touches `data/`, `logs/`, `.env`) |
| Watch the app | `ssh root@<box> docker logs -f aladi-web-1` |
| Check the weekly run | on the box: `tail /srv/aladi/logs/cron.log`, `ls /srv/aladi/logs/`, `ls /srv/aladi/data/eng/snapshots/` (and `data/ita/…`) — cron line via `crontab -l` (Sundays 07:30 Europe/Madrid) |
| Run the weekly job by hand | on the box: `cd /srv/aladi && docker compose -f deploy/compose.yaml run --rm jobs` (a full scrape of every language — don't do this casually) |
| Sync one language only | on the box: `docker compose -f deploy/compose.yaml run --rm -e ALADI_LANGS=ita jobs` |
| Add or change a login | `python3 server.py --hash-password` → write `name:hash` into `ALADI_USERS` in `/srv/aladi/.env` **with every `$` doubled to `$$`**, then on the box `docker compose -f deploy/compose.yaml up -d` |
| Sign everyone out | change `ALADI_SECRET` in `/srv/aladi/.env`, then `up -d` |
| Restart | on the box: `cd /srv/aladi && docker compose -f deploy/compose.yaml restart` |

Things that will bite: `.env` values are interpolated by compose (hence `$$`); the
ledger's stack is compose project `deploy`, so never run `down --remove-orphans` on the
box; the box's `data/` is the source of truth — never rsync `data/` from the Mac again.
Local dev is unchanged: `python3 server.py` on localhost with no login.

**One-time layout migration (done 2026-09-09).** Data moved from a single
catalogue to per-language directories. On the box, before deploying the
multi-language code:

```bash
cd /srv/aladi/data && mkdir -p eng \
  && mv snapshots diffs enrichment.jsonl eng/     # libraries.json stays at top level
```

Skip this on a fresh install — the scripts create what they need.
