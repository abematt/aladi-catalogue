#!/bin/zsh
# Weekly Aladi catalogue sync: scrape a fresh snapshot, then diff vs the previous one.
# Invoked by launchd (com.abraham.aladi-weekly) — or run by hand.
set -e
cd "$(dirname "$0")"
mkdir -p logs
LOG="logs/weekly-$(date +%Y-%m-%d).log"
echo "=== aladi weekly run $(date) ===" >> "$LOG"
/usr/bin/python3 -u scraper.py >> "$LOG" 2>&1
/usr/bin/python3 -u diff.py >> "$LOG" 2>&1 || true
echo "=== done $(date) ===" >> "$LOG"
