#!/usr/bin/env bash
#
# pull-from-main.sh — deploy the latest origin/main into this NON-git checkout.
#
# /srv/abstractgpt/abstractgpt is a plain directory (no .git), so we can't
# git-pull in place. Instead we clone origin/main to a temp dir and swap in the
# fresh api/ and app/.
#
# Steps:
#   1. Shallow-clone origin/main to a temp dir; verify it has api/ and app/.
#   2. Snapshot the current api/ and app/ into prev/<timestamp>/ (rollback).
#   3. Swap the fresh api/ and app/ into place.
#   4. Build the frontend (yarn && yarn build).
#   5. Restart the API service (streams the rolling log).
#
# The clone happens BEFORE we touch the running copy, so a failed/empty clone
# never leaves the site without api/ or app/.
#
#   ./scripts/pull-from-main.sh
#   ROOT=/some/path REPO_URL=git@github.com:AbstractEndeavors/abstractgpt.git ./scripts/pull-from-main.sh
#
set -euo pipefail

ROOT="${ROOT:-/srv/abstractgpt/abstractgpt}"
REPO_URL="${REPO_URL:-https://github.com/AbstractEndeavors/abstractgpt.git}"
BRANCH="${BRANCH:-main}"
SERVICE="${SERVICE:-6092_abstractgpt_api}"
TS="$(date '+%Y%m%d_%H%M%S')"
PREV="$ROOT/prev/$TS"

if [[ ! -d "$ROOT" ]]; then
  echo "error: $ROOT does not exist" >&2
  exit 1
fi

# Temp clone dir on the same filesystem as ROOT so the final swap is a fast mv.
TMP="$(mktemp -d "$ROOT/.deploy.XXXXXX")"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

# 1. Clone latest main (retry on transient network failures).
echo "Cloning $REPO_URL ($BRANCH)…"
n=0
until git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$TMP/repo"; do
  n=$((n + 1))
  if (( n > 4 )); then echo "error: git clone failed" >&2; exit 1; fi
  echo "clone failed (attempt $n), retrying…"; rm -rf "$TMP/repo"; sleep $((2 ** n))
done

# Verify the clone actually contains what we're about to deploy.
for d in api app; do
  if [[ ! -d "$TMP/repo/$d" ]]; then
    echo "error: cloned repo is missing $d/ — aborting before touching live files" >&2
    exit 1
  fi
done
NEW_REV="$(git -C "$TMP/repo" rev-parse --short HEAD)"

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

# 3. Swap the fresh api/ and app/ into place.
echo "Installing fresh api/ and app/ from $NEW_REV…"
mv "$TMP/repo/api" "$ROOT/api"
mv "$TMP/repo/app" "$ROOT/app"

# 4. Build the frontend.
echo "Building frontend…"
cd "$ROOT/app"
yarn
yarn build

echo "✓ Deployed $BRANCH ($NEW_REV). Rollback snapshot: $PREV"

# 5. Restart the API service. This streams the rolling log and blocks, so it
#    goes last — keep nothing after it.
echo "Restarting service $SERVICE…"
cd "$ROOT"
restart_view_service "$SERVICE"
