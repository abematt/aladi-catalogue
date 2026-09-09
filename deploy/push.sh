#!/usr/bin/env bash
# Sync the code to the box and (re)start the web stack. No GitHub needed.
#   deploy/push.sh root@<box>
# data/, logs/ and .env are deliberately NOT synced: once the box runs the weekly
# scrape, its data/ is the source of truth (seed it once by hand with rsync).
set -euo pipefail
HOST=${1:?usage: deploy/push.sh user@host}
DEST=/srv/aladi
cd "$(dirname "$0")/.."

rsync -az --delete \
  --exclude .git --exclude .vscode --exclude '__pycache__' \
  --exclude data --exclude logs --exclude .env --exclude nohup.out --exclude .DS_Store \
  ./ "$HOST:$DEST/"

ssh "$HOST" "cd $DEST && docker compose -f deploy/compose.yaml up -d --build && docker compose -f deploy/compose.yaml ps"
