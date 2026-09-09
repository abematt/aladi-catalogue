> **Stale (2026-09-09):** the deployment is live; see the Deployment section of CLAUDE.md. Kept for the history of the self-build phases.

# Session handoff — Hetzner self-build (updated 2026-08-09, evening)

Continuity doc for resuming the deployment project in a fresh Claude session.
Read alongside CLAUDE.md (repo briefing) and the session memory.

## The project

Deploy this app to a Hetzner VPS per the 7-phase self-build roadmap. Abraham
is building it HIMSELF to learn — that's the point, not the deployment.

## The working agreement (strict)

1. Claude publishes a **guide per phase as an Artifact page** — spec, concepts,
   gotchas, checkpoint commands, self-quiz. Guides are specs, **never finished
   files**. One phase at a time; phase N+1 publishes when N's checkpoint and
   quiz pass.
2. Abraham writes every artifact (Dockerfile, compose.yaml, Terraform, …) and
   **runs every command in his own terminal**. Claude reviews output and files
   like a PR. (Lesson learned: Claude ran the Phase 1 checkpoint itself and
   the `-v` flag never landed — don't repeat that. Phase 2's checkpoint was
   run entirely by him; that's the standard.)
3. When he's confused: drop jargon, design a small experiment he runs himself.
   Park deeper theory on `docs/dive-deeper.md` instead of teaching everything
   in the moment.

## Phase guides (Artifacts)

- Phase 1 — Containerize: https://claude.ai/code/artifact/c862545d-3c29-4e56-bf01-de49ffadea60
- Phase 2 — Compose: https://claude.ai/code/artifact/a72bf3a8-36d9-41da-a1a4-99bb1a6da286
- Phase 3 — VPS by hand: https://claude.ai/code/artifact/f5baf8ba-d62e-4fa5-8d6a-73e077997c49
- Phases 4–7: not yet published (Tunnel+Access → Terraform → CI/CD → loose ends).
- Visual design is shared across all guide pages; the Phase 3 HTML source is
  the freshest copy (this session's scratchpad, `phase-3-vps-by-hand.html`) —
  rebuild from a published artifact via WebFetch if needed.

## Status

**Phase 1 — DONE** (commit `f8a88ad`, 2026-08-09). Dockerfile, .dockerignore,
ALADI_BIND env-var bind in server.py. Checkpoint + quiz passed.

**Phase 2 — DONE** (2026-08-09, not yet committed — see "Repo state"):
- `compose.yaml`: web (build+image aladi, `"127.0.0.1:18377:8377"`,
  ./data:/app/data, restart: unless-stopped, init: true) + jobs (image reuse,
  profiles: ["jobs"], data+logs mounts, init: true, no restart,
  command: ./run_weekly.sh).
- Option B for the weekly entrypoint: `run_weekly.sh` made portable
  (#!/bin/sh, bare python3) + `COPY run_weekly.sh .` in Dockerfile. He chose
  file logging, kept via the ./logs mount — Mac launchd behavior unchanged.
- Checkpoint passed in his terminal: only web on `up` ✓, curl ✓,
  `time docker compose stop` = 0.4s (was 10.2s — init: true payoff) ✓,
  jobs no-op wiring proof ✓, data survived `down` ✓.
- Quiz: all five closed. Weak spots worked through: restart-policy failure
  modes, Docker-owns-the-grace-period (not SIGTERM), tini explained, bind
  mount `.` character, EXPOSE-does-nothing misconception killed, two-doorways
  (published port vs compose-network port — web:8377 not web:18377).

**Phase 3 — IN PROGRESS.** Guide published (link above). He rents a Hetzner
box (CAX11-vs-CX22 is his decision, arch teaching attached), Cloud Firewall
inbound 22 only, Docker via official apt repo, **repo must first be pushed to
GitHub — it has NO remote as of this handoff** (private repo + PAT or deploy
key for the clone), rsync data/ from Mac (never seed by scraping), compose up
on the box, cron owns Sunday 07:30 (UTC decision his), no-op cron wiring test,
then retire Mac launchd job same day. Checkpoint = ssh -L tunnel + two failing
public curls + launchctl print "not found". Delayed proof: first unattended
Sunday run on the box.

## Standing constraints

- Politeness rules in CLAUDE.md are non-negotiable. **No extra full scrapes**
  — this now includes: never seed the VPS by scraping (rsync from Mac), and
  never have Mac launchd + VPS cron both live across a Sunday. Wiring tests
  use `enrich.py --limit=20` (a no-op at full coverage).
- Mac launchd job (com.abraham.aladi-weekly) fires Sundays 07:30 and owns the
  schedule until the VPS cron line is live; retire it the same day.
- His laptop server usually holds port 8377 — that's why compose publishes
  host 18377 and the Phase 3 tunnel example uses local port 28377.

## Repo state at handoff

- Committed through `f8a88ad` on main. **Uncommitted Phase 2 work**: modified
  `Dockerfile`, `run_weekly.sh`; untracked `compose.yaml`,
  `docs/session-handoff.md`. `.vscode/` untracked (leave it). Committing is
  his job — remind, don't do it.
- **No git remote configured** — GitHub push is a Phase 3 prerequisite.
- `docs/dive-deeper.md` — his parked-topics list. Extended this session with:
  compose networking (service DNS vs published ports, EXPOSE-is-a-label);
  bind vs named/anonymous volumes; YAML type-guessing; SSH bundle (keypairs,
  fingerprints, tunnels, deploy keys vs PATs); why non-root matters; CPU
  architectures / multi-arch images. The last three are pre-parked from the
  Phase 3 guide, not yet exercised.

## Resuming

Next concrete action: he commits Phase 2, pushes the repo to a new private
GitHub repo, then works the Phase 3 guide. He brings console decisions +
command output + the five quiz answers → review like a PR → publish Phase 4
artifact (same visual design).
