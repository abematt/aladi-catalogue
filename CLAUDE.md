# CLAUDE.md

Personal project (Abraham + girlfriend, no other users): a local web app over the
**Aladí** library OPAC (aladi.diba.cat — Barcelona province municipal libraries
network), holding every **English-language item** (~64k: books, CDs, vinyl, DVDs,
scores, board games, magazines, maps, video games) with search/filters the real
site doesn't have. Standalone repo — the Measure workspace guidance in ancestor
CLAUDE.md files does not apply here.

## Components (all pure Python stdlib; the one binary dep is `yaz-client`)

| File | Job |
|---|---|
| `scraper.py` | Weekly full sync of the OPAC → `data/snapshots/YYYY-MM-DD.json` + `.csv`. Broad boolean keyword query + ~40 residual `AND NOT` sweeps per material type (the OPAC caps results at 32k and has no list-all). Resumable (`--resume`), `--materials=a,j,...` to scope. |
| `enrich.py` | Per-record MARC data via **Z39.50** (`yaz-client`, port 210, db INNOPAC — the sanctioned machine interface). Derives `form`/`aud` (008), genre buckets from Catalan subject headings + English titles, and **holding-library codes** (907 `$i`). Incremental; `--rederive` recomputes genres locally from stored subjects without network. |
| `diff.py` | Diffs two newest snapshots → `data/diffs/`. |
| `server.py` | App + JSON API on **localhost:8377**: `/api/catalogue`, `/api/enrichment`, `/api/libraries`, `/api/diffs`, `/api/availability?bib=` (live per-copy status proxied from the record page, 5-min cache). |
| `app/index.html` | Single-file UI: type chips, genre/audience chips (books), decade/year, library picker ("my libraries" in localStorage — selecting libraries IS the filter), Google-search buttons, live availability on row click, CSV export, weekly-changes tab. |
| `run_weekly.sh` | scrape → diff → enrich; scheduled by launchd `com.abraham.aladi-weekly` (Sun 07:30, plist in repo + `~/Library/LaunchAgents`). |

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

## Deployment (in progress — Abraham is building this HIMSELF to learn)

Target: Hetzner VPS + Docker Compose (web + cloudflared + jobs-profile
containers, shared data volume, host cron weekly), Cloudflare Tunnel + Access
(Google login, two-email allow policy, no inbound ports except SSH), Terraform
(hcloud + cloudflare providers), GitHub Actions → GHCR → SSH deploy.
**Do not scaffold these files for him** — review what he writes, explain
concepts, point at breakage. Known code prerequisite: `server.py` binds
127.0.0.1; container needs an env-var bind address. Once the server owns the
weekly run, disable the Mac launchd job.
