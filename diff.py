#!/usr/bin/env python3
"""Compare the two most recent catalogue snapshots and write a diff report.

Usage:
    python3 diff.py                          # English, two newest snapshots
    python3 diff.py --lang=ita               # Italian, two newest snapshots
    python3 diff.py 2026-08-08 2026-08-15    # two specific dates

Writes data/<lang>/diffs/<from>__<to>.json with added / removed / changed
records and prints a human summary.
"""
import json
import os
import sys

import langs

ROOT = os.path.dirname(os.path.abspath(__file__))

FIELDS = ["title", "author", "pub", "year", "isbn", "bib"]


def load(snap_dir, date):
    with open(os.path.join(snap_dir, f"{date}.json")) as f:
        d = json.load(f)
    return {row[5]: row for row in d["items"]}


def main():
    lang = langs.resolve()
    ddir = langs.data_dir(ROOT, lang)
    snap_dir = os.path.join(ddir, "snapshots")
    diff_dir = os.path.join(ddir, "diffs")
    dates = [a for a in sys.argv[1:] if not a.startswith("--")]

    snaps = sorted(f[:-5] for f in os.listdir(snap_dir)
                   if f.endswith(".json")) if os.path.isdir(snap_dir) else []
    if len(dates) == 2:
        a, b = dates
    elif len(snaps) >= 2:
        a, b = snaps[-2], snaps[-1]
    else:
        print(f"[{lang['code']}] need at least two snapshots to diff; have:", snaps)
        return
    old, new = load(snap_dir, a), load(snap_dir, b)
    added = [new[k] for k in new.keys() - old.keys()]
    removed = [old[k] for k in old.keys() - new.keys()]
    changed = [{"before": old[k], "after": new[k]}
               for k in old.keys() & new.keys() if old[k] != new[k]]
    added.sort(key=lambda r: r[0].casefold())
    removed.sort(key=lambda r: r[0].casefold())
    report = {"from": a, "to": b, "lang": lang["code"],
              "counts": {"from": len(old), "to": len(new),
                         "added": len(added), "removed": len(removed), "changed": len(changed)},
              "added": added, "removed": removed, "changed": changed}
    os.makedirs(diff_dir, exist_ok=True)
    out = os.path.join(diff_dir, f"{a}__{b}.json")
    with open(out, "w") as f:
        json.dump(report, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[{lang['code']}] {a} -> {b}: {len(old)} -> {len(new)} records "
          f"(+{len(added)} added, -{len(removed)} removed, ~{len(changed)} changed)")
    print(f"report: {out}")


if __name__ == "__main__":
    main()
