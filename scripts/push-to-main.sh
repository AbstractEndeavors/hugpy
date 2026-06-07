#!/usr/bin/env bash
#
# push-to-main.sh — commit everything in this repo and push it to origin/main.
#
# Built for the server checkout at /srv/hugpy where files get edited in place.
# Run it with an optional commit message:
#
#     ./scripts/push-to-main.sh "fix slot autofit + worker tweaks"
#
# With no message it uses a timestamped default. Override the repo path with
# REPO=/some/path ./scripts/push-to-main.sh
#
set -euo pipefail

REPO="${REPO:-/srv/hugpy}"
BRANCH="main"
MSG="${*:-deploy: $(date '+%Y-%m-%d %H:%M:%S %Z')}"

cd "$REPO"

# Must be a git repo.
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "error: $REPO is not a git repository" >&2
  exit 1
fi

# Make sure we're on main (create a tracking branch if needed).
current="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$current" != "$BRANCH" ]]; then
  echo "Switching from '$current' to '$BRANCH'…"
  git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH" --track "origin/$BRANCH"
fi

# Drop anything that's tracked but should be ignored (build output, deps,
# logs, __pycache__). On first run against an old checkout these may still be
# committed; --cached untracks them without deleting the files on disk.
tracked_ignored="$(git ls-files -i -c --exclude-standard || true)"
if [[ -n "$tracked_ignored" ]]; then
  echo "Untracking ignored files that were previously committed…"
  printf '%s\n' "$tracked_ignored" | sed 's/^/  - /'
  printf '%s\n' "$tracked_ignored" | tr '\n' '\0' | xargs -0 -r git rm -r --cached --quiet
fi

# Nothing to do?
if [[ -z "$(git status --porcelain)" ]]; then
  echo "Working tree clean — nothing to commit."
else
  echo "Staging and committing changes…"
  # .gitignore keeps app/dist, app/node_modules, app/yarn.lock, *.log and
  # __pycache__ out of `git add -A`.
  git add -A
  git commit -m "$MSG"
fi

# Push, integrating remote changes if the push is rejected (non-fast-forward).
push() {
  git push origin "$BRANCH"
}

n=0
until push; do
  n=$((n + 1))
  if (( n > 4 )); then
    echo "error: push failed after retries" >&2
    exit 1
  fi
  echo "Push rejected/failed (attempt $n). Rebasing on origin/$BRANCH and retrying…"
  # --autostash protects any stray uncommitted changes; --ff-only style rebase
  # keeps history linear. If this stops on a conflict, resolve it then re-run.
  git pull --rebase --autostash origin "$BRANCH"
  sleep $((2 ** n))
done

echo "✓ Pushed to origin/$BRANCH ($(git rev-parse --short HEAD))"
