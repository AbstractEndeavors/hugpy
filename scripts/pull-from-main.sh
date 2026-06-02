#!/usr/bin/env bash
#
# pull-from-main.sh — deploy the latest origin/main to this checkout.
#
# Steps:
#   1. Snapshot the current api/ and app/ into prev/<timestamp>/ (rollback point).
#   2. Recreate api/ and app/ fresh from origin/main (git reset --hard).
#   3. Build the frontend (yarn && yarn build).
#   4. Restart the API service.
#
# Untracked, ignored files (app/node_modules, app/dist, *.log, __pycache__) are
# left in place by the reset, so yarn stays fast. The prev/ snapshots are also
# untracked and untouched.
#
#   ./scripts/pull-from-main.sh
#   ROOT=/some/path ./scripts/pull-from-main.sh
#
set -euo pipefail

ROOT="${ROOT:-/srv/abstractgpt/abstractgpt}"
BRANCH="main"
SERVICE="6092_abstractgpt_api"
TS="$(date '+%Y%m%d_%H%M%S')"
PREV="$ROOT/prev/$TS"

cd "$ROOT"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "error: $ROOT is not a git repository" >&2
  exit 1
fi

# 1. Fetch latest main (retry on transient network failures).
echo "Fetching origin/$BRANCH…"
n=0
until git fetch origin "$BRANCH"; do
  n=$((n + 1))
  if (( n > 4 )); then echo "error: git fetch failed" >&2; exit 1; fi
  echo "fetch failed (attempt $n), retrying…"; sleep $((2 ** n))
done

# 2. Snapshot the currently-deployed api/ and app/ before replacing them.
echo "Backing up current api/ and app/ -> $PREV"
mkdir -p "$PREV"
for d in api app; do
  if [[ -e "$ROOT/$d" ]]; then
    mv "$ROOT/$d" "$PREV/$d"
  else
    echo "  note: $d/ does not exist yet (nothing to back up)"
  fi
done

# 3. Recreate everything (api/, app/, …) fresh from origin/main. The dirs we
#    just moved are tracked, so the hard reset restores them from github.
#    Untracked files — including the new prev/ snapshot — are not touched.
echo "Resetting working tree to origin/$BRANCH…"
git reset --hard "origin/$BRANCH"

# 4. Build the frontend.
echo "Building frontend…"
cd "$ROOT/app"
yarn
yarn build

# 5. Restart the API service.
echo "Restarting service $SERVICE…"
cd "$ROOT"
restart_view_service "$SERVICE"

echo "✓ Deployed origin/$BRANCH ($(git rev-parse --short HEAD)). Rollback snapshot: $PREV"
