# CLAUDE.md

Personal project (Abraham + girlfriend, no other users): a local web app over the
**Aladí** library OPAC (aladi.diba.cat — Barcelona province municipal libraries
network), holding every item in a chosen language (books, CDs, vinyl, DVDs,
scores, board games, magazines, maps, video games) with search/filters the real
site doesn't have. Standalone repo — the Measure workspace guidance in ancestor
CLAUDE.md files does not apply here.

**Two catalogues, switchable in the app header:** English (`eng`, ~64.5k items)
and Italian (`ita`, ~7.7k, added 2026-09-09). `langs.py` is the registry — the
one place that knows which catalogues exist, with each language's broad query
and residual sweeps. Every script defaults to English and takes `--lang=<code>`;
state is per language under `data/<lang>/` (`snapshots/`, `diffs/`,
`enrichment.jsonl`). `data/libraries.json` is shared, as is the app's "my
libraries" selection — branch codes are language-independent. Adding a language
= one entry in `langs.py` + a scrape; the server and UI pick it up from
`/api/languages`. **Before adding one, read
[`docs/adding-a-language.md`](docs/adding-a-language.md)** — it has the runbook,
the sizing check (Catalan is at the OPAC's 32k cap and Spanish 502s on a broad
query, so neither is a drop-in), and the genre-rule traps.

## Components (all pure Python stdlib; the one binary dep is `yaz-client`)

| File | Job |
|---|---|
| `langs.py` | Language registry: per-language `main_q` + `residual_terms`, `resolve()` for `--lang=`/`$ALADI_LANG`, `data_dir()` for `data/<lang>/`. |
| `scraper.py` | Weekly full sync of the OPAC → `data/<lang>/snapshots/YYYY-MM-DD.json` + `.csv`. Broad boolean keyword query + residual `AND NOT` sweeps per material type (the OPAC caps results at 32k and has no list-all). Resumable (`--resume`), `--materials=a,j,...` to scope, `--lang=` to pick the catalogue. |
| `enrich.py` | Per-record MARC data via **Z39.50** (`yaz-client`, port 210, db INNOPAC — the sanctioned machine interface). Derives `form`/`aud` (008), genre buckets from Catalan subject headings + titles, and **holding-library codes** (907 `$i`). Genre rules key off *Catalan* subjects so they work for every language; only the tech/history title fallbacks are language-specific (English + Italian stems). Incremental; `--rederive` recomputes genres locally from stored subjects without network. |
| `diff.py` | Diffs two newest snapshots → `data/<lang>/diffs/`. |
| `server.py` | App + JSON API on port 8377 (bind via `ALADI_BIND`, default localhost). `/api/catalogue`, `/api/enrichment`, `/api/snapshots`, `/api/diffs` all take `?lang=` (default `eng`, unknown code → 400 rather than a silent fallback); `/api/languages` lists the catalogues with counts; `/api/libraries` and `/api/availability?bib=` (live per-copy status proxied from the record page, 5-min cache) are language-independent. Optional in-app login (`/login`, `/logout`, signed session cookie) when `ALADI_USERS` is set — see Deployment. |
| `app/index.html` | Single-file UI: language switch in the wordmark (`ALADÍ / english · italiano`, choice in localStorage), type chips, genre/audience chips (books), decade/year, library picker ("my libraries" in localStorage — selecting libraries IS the filter), Google-search buttons, live availability on row click, CSV export, weekly-changes tab. |
| `run_weekly.sh` | Per language: scrape → diff → enrich. Languages from `$ALADI_LANGS` (default `eng ita`). Runs from root's crontab on the box (Sun 07:30 Europe/Madrid). |

`data/` and `logs/` are gitignored state. `data/libraries.json` maps the 249
branch codes → names (scraped from the OPAC search form).

## Politeness constraints (non-negotiable)

- aladi.diba.cat robots.txt disallows `/search` and `/record=` (anti-indexing
  intent). Personal weekly cadence only, scraper stays at 4 workers, never host
  a public mirror. ~5k requests/full run has drawn zero blocks.
- Z39.50 is the preferred bulk path (built for machine queries; result sets cap
  at 500 per search, so it enriches per-record, not enumerates).
- Availability lookups are on-demand only (one per click), never bulk-polled.

## Gotchas learned the hard way

- Author lines carry lifespans ("Grafton, Sue, 1940-2017") — imprint detection
  must not treat them as publisher/year (template order: author line, then imprint).
- Catalan plurals shift spelling (policíaca→policíaques, c→qu): genre rules use
  stems, and the middot (l·l) is not a period.
- yaz batch sessions can time out silently → dropped batches; enrich is
  idempotent, rerun fills gaps (timeouts now printed).
- `$i none` in 907 = record with no copies attached (on-order); filtered out.
- The `hidden` attribute loses to `display:flex` — `.typechips[hidden]` CSS rule.
- `S171*eng` in OPAC URLs is the site's **interface** language and stays `eng`
  for every catalogue; the *item* language is the `l=` query parameter. Record
  permalinks keep `~S171*eng` regardless of the item's language.
- Genre keys are substring matches on **diacritic-folded** subjects, so folding
  can collapse two different words: `italia` matches both "Italià" (the
  language) and "Itàlia" (the country), and `illustrator` matches
  "illustrators"/"illustratore". Space-padding fixes the second (a word that
  only appears mid-string) but not the first, because both forms can end a
  heading — there, position is the signal, since the catalogue writes a
  language as the heading ("Italià — Gramàtica") and a country as a
  subdivision ("Música popular — Itàlia"). Hence `is_language_subject()`.
  After any rule change, `--rederive` both languages and diff the genre
  counts before/after; a rule that looks right can move hundreds of records.
- Switching language in the UI must invalidate the diff tab's load-once cache
  and guard in-flight fetches (a `loadSeq` counter) — otherwise a slow response
  for the language you just left overwrites the new one.

## Deployment (live since 2026-09-09)

Runs as the third app on Abraham's Hetzner box (<box>, the same one as
`~/ledger`; see `ledger/docs/server-handoff.md` for the box). URL:
**https://<private host>**, behind the box's shared Caddy
(`/srv/caddy/sites/aladi.caddy`: `reverse_proxy aladi:8377`, noindex header).
No published ports; TLS lives in Caddy.

**Login is in-app** (`server.py`): a styled `/login` page, signed 30-day session
cookie, `/logout`, per-IP lockout after 6 failures. Enabled when `ALADI_USERS`
is set (`name:pbkdf2$...` pairs) plus `ALADI_SECRET`; both live in
`/srv/aladi/.env` on the box (chmod 600, gitignored, excluded from push.sh).
Unset → no login, which is the local-dev default. New hash:
`python3 server.py --hash-password`. **Escape every `$` in `.env` as `$$`** —
compose interpolates env files. Only Abraham and Fefi have users.

- `deploy/compose.yaml` — server stack (`name: aladi`; `web` joins the external `web`
  network with alias `aladi`; `jobs` profile for the weekly run). Root `compose.yaml`
  is the local dev stack.
- `deploy/push.sh root@<box>` — rsync code + `up -d --build`. **Excludes
  `data/` and `logs/`**: the box's `data/` is the source of truth (seeded once by
  rsync from the Mac on 2026-09-09). Never rsync data Mac → box again.
- Weekly job: root's crontab on the box, `30 7 * * 0` (box TZ Europe/Madrid),
  `docker compose -f deploy/compose.yaml run --rm jobs`, stdout in `logs/cron.log`.
  The Mac launchd job `com.abraham.aladi-weekly` was retired the same day (plist
  moved to `~/Library/LaunchAgents.retired/`; the copy in this repo is inert).
- The Mac's `data/` is now a frozen copy for local dev only.
- Day-to-day operations (logs, redeploy, add a user, cron check): README → "Running in production".
