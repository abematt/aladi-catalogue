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
