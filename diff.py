#!/usr/bin/env python3
"""Compare the two most recent catalogue snapshots and write a diff report.

Usage:
    python3 diff.py                 # diff two newest snapshots
    python3 diff.py 2026-08-08 2026-08-15   # diff two specific dates

Writes data/diffs/<from>__<to>.json with added / removed / changed records
and prints a human summary.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(ROOT, "data", "snapshots")
DIFF_DIR = os.path.join(ROOT, "data", "diffs")

FIELDS = ["title", "author", "pub", "year", "isbn", "bib"]


def load(date):
    with open(os.path.join(SNAP_DIR, f"{date}.json")) as f:
        d = json.load(f)
    return {row[5]: row for row in d["items"]}


def main():
    snaps = sorted(f[:-5] for f in os.listdir(SNAP_DIR) if f.endswith(".json"))
    if len(sys.argv) == 3:
        a, b = sys.argv[1], sys.argv[2]
    elif len(snaps) >= 2:
        a, b = snaps[-2], snaps[-1]
    else:
        print("Need at least two snapshots to diff; have:", snaps)
        return
    old, new = load(a), load(b)
    added = [new[k] for k in new.keys() - old.keys()]
    removed = [old[k] for k in old.keys() - new.keys()]
    changed = [{"before": old[k], "after": new[k]}
               for k in old.keys() & new.keys() if old[k] != new[k]]
    added.sort(key=lambda r: r[0].casefold())
    removed.sort(key=lambda r: r[0].casefold())
    report = {"from": a, "to": b,
              "counts": {"from": len(old), "to": len(new),
                         "added": len(added), "removed": len(removed), "changed": len(changed)},
              "added": added, "removed": removed, "changed": changed}
    os.makedirs(DIFF_DIR, exist_ok=True)
    out = os.path.join(DIFF_DIR, f"{a}__{b}.json")
    with open(out, "w") as f:
        json.dump(report, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{a} -> {b}: {len(old)} -> {len(new)} records "
          f"(+{len(added)} added, -{len(removed)} removed, ~{len(changed)} changed)")
    print(f"report: {out}")


if __name__ == "__main__":
    main()
