# Aladí English Catalogue

A local, browsable catalogue of **every English-language item** in the Aladi OPAC
(aladi.diba.cat — the Barcelona province municipal libraries network) — books,
music CDs, vinyl, DVDs, printed scores, board games, magazines, maps, video
games — with weekly snapshots, week-over-week diffs, and **on-demand live
availability** (which copies are on the shelf vs checked out, per library).
First full snapshot (2026-08-08): ~61k items, of which 32,447 books.

Built because the OPAC has no "browse everything in English" view — its language
filter only applies on top of a keyword search.

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
| `scraper.py` | Full sync → `data/snapshots/YYYY-MM-DD.json` + `.csv`. ~2,500 requests, ~45 min at the default 4 workers. Resumable (`--resume`). |
| `diff.py` | Compares the two newest snapshots → `data/diffs/<from>__<to>.json`. |
| `server.py` | Serves the app + `/api/catalogue`, `/api/diffs`, `/api/availability?bib=…`. |
| `run_weekly.sh` | scraper + diff, logged to `logs/`. |

### How the scrape covers "everything"

The OPAC (classic Innovative Millennium) requires a keyword and caps results at
32,000, so: one broad boolean query (`and OR the OR a OR in OR de OR of`,
language=English, material=Book, ≈28.6k records) plus ~40 residual sweeps
(`term AND NOT (main)`) to catch records containing none of the main words.
Deduped by bib record id. First full run: **32,447 unique books** (2026-08-08).
Coverage is near-total but not provably complete — a record whose indexed text
contains none of the ~46 probe words would be missed.

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
