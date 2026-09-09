#!/bin/sh
# Weekly Aladi catalogue sync, one pass per catalogue language: scrape a fresh
# snapshot, diff it against the previous one, then enrich the new records.
# Invoked by cron on the Hetzner box (see deploy/compose.yaml "jobs") — or by hand.
#
# Languages come from $ALADI_LANGS (space-separated); override to run just one:
#   ALADI_LANGS=ita ./run_weekly.sh
set -e
cd "$(dirname "$0")"
mkdir -p logs
LOG="logs/weekly-$(date +%Y-%m-%d).log"
LANGS="${ALADI_LANGS:-eng ita}"
echo "=== aladi weekly run $(date) — langs: $LANGS ===" >> "$LOG"
for lang in $LANGS; do
  echo "--- $lang ---" >> "$LOG"
  python3 -u scraper.py --lang="$lang" >> "$LOG" 2>&1
  python3 -u diff.py --lang="$lang" >> "$LOG" 2>&1 || true
  # enrich new records with genre + holding-library data (incremental)
  python3 -u enrich.py --lang="$lang" >> "$LOG" 2>&1 || true
done
echo "=== done $(date) ===" >> "$LOG"
