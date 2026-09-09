# Dive-deeper list

Topics parked during the Hetzner self-build. High-level understanding exists;
each deserves a proper session later. Add freely; strike through when done.

## Networking: bind addresses, interfaces, loopback
- Current understanding: 127.0.0.1 = same-machine only; 0.0.0.0 = any interface,
  anyone who can route a packet can connect.
- Underneath: what a network interface actually is (`lo` vs `eth0`), what
  "binding" a socket means, network namespaces (why a container has its own
  loopback), how `-p` port-publishing forwards to the container's eth0, and
  host-side bind (`-p 127.0.0.1:8377:8377` vs `-p 8377:8377`).

## Processes and PIDs — what PID 1 actually is
- Current understanding: every process gets a number (PID); PID 1 is the first
  process in a container; docker stop sends SIGTERM to PID 1 only, and the
  kernel won't deliver a signal to PID 1 unless it installed a handler —
  hit this live 2026-08-09: exec-form CMD still took the full 10s grace period
  because python has no SIGTERM handler (Ctrl-C works — python handles SIGINT).
- Underneath: the Unix process model (fork/exec, parent→child tree), what init
  is on a real Linux system and why PID 1 is special (orphan adoption, zombie
  reaping), PID namespaces (why the container's python thinks it's PID 1 while
  the host sees a normal PID), and the fixes: `docker run --init` / compose
  `init: true` (tini), or installing a signal handler yourself.

## CMD shell form vs exec form (PID 1 and signals)
- Current understanding: exec form makes python PID 1 so SIGTERM reaches it;
  shell form wraps in `/bin/sh -c` which doesn't forward signals → 10s hang
  then SIGKILL on every `docker stop`.
- Underneath: what PID 1 means in Unix, signal delivery and default handlers,
  why PID 1 has special signal rules, zombie reaping, when you'd want an init
  process (`docker run --init`, tini).

## CMD vs ENTRYPOINT
- Current understanding: CMD = replaceable default (words after image name
  replace it — how one image runs server AND jobs); ENTRYPOINT = always runs,
  run-line words become its arguments (for images that ARE one program).
- Underneath: how the two combine when both are set (ENTRYPOINT + CMD as
  default args), `--entrypoint` override, exec vs shell form applies here too.

## Compose networking: service DNS vs published ports (the two doorways)
- Current understanding (Phase 2 quiz): a container has two separate doorways.
  `ports:` publishes a hole from the HOST into the container (127.0.0.1:18377
  → 8377) — for me and curl. On the compose private network, the service name
  is a hostname and you dial the port the process actually listens on
  (cloudflared → `web:8377`, never 18377; the ports: line could vanish and it
  still works). EXPOSE in a Dockerfile is a label — it opens nothing; a
  process listening (server.py on 0.0.0.0:8377) is what opens a port.
- Underneath: Docker's embedded DNS server, what network `compose up` actually
  creates (`<project>_default` bridge), how port-publishing is NAT/iptables
  under the hood, container `eth0` vs host interfaces — ties into the
  bind-address topic above.

## Mounts: bind mounts vs named/anonymous volumes
- Current understanding (Phase 2 quiz): `./data:/app/data` — the `.` makes the
  left side a real folder on my Mac → a BIND mount, a two-way window; data
  lives on the host, so `docker compose down` (which deletes container +
  network) never touches it. A single path with no colon = an anonymous
  volume Docker owns — near-opposite behavior.
- Underneath: named volumes (`volumes:` top-level key) — where Docker stores
  them, when they beat bind mounts (permissions, performance on Mac), the
  lifecycle of anonymous volumes, `docker volume ls/prune`.

## YAML's type-guessing (why port mappings get quoted)
- Current understanding: indentation IS structure (2 spaces, no tabs); always
  quote `"host:container"` port strings.
- Underneath: YAML 1.1's implicit typing — base-60 "sexagesimal" numbers, the
  Norway problem (`no` → false), why compose docs say quote-your-ports, what
  YAML 1.2 changed.

## SSH: keypairs, fingerprints, tunnels, and repo auth (parked from the Phase 3 guide)
- Current understanding (guide level, not yet exercised): public half = lock
  on the server, private half = key that never leaves the Mac; first-connect
  fingerprint prompt = pinning the server's identity; `ssh -L` = extension
  cord through the one open port; private-repo cloning needs a fine-grained
  PAT or a deploy key.
- Underneath: asymmetric crypto in plain words (why the public half can be
  public), ssh-agent, known_hosts, `-L` vs `-R` vs `-D`, deploy keys vs PATs
  vs SSH-agent forwarding — trade-offs and revocation.

## Why non-root users matter on a server (parked from the Phase 3 guide)
- Current understanding: Phase 3 runs everything as root on the VPS as an
  accepted simplification for a one-app personal box; proper user hygiene is
  Phase 7 material.
- Underneath: blast radius, sudo, the docker group's root-equivalence gotcha,
  systemd user services, what "hardening" actually buys on a box like this.

## CPU architectures and multi-arch images (will bite in Phase 6)
- Current understanding: an image is a compiled artifact built FOR an
  architecture — Mac = arm64, most servers/GitHub runners = x86_64; Phase 3
  sidesteps it by building ON the box, so image and machine always match.
- Underneath: what actually differs in the binaries, multi-arch manifests
  (how `python:3.12-slim` serves both), buildx and QEMU emulation, the
  cost/speed trade-offs Phase 6 must pick between.
