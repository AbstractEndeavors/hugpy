#!/usr/bin/env bash
#
# pull-from-main.sh — deploy the latest origin/main into the /srv/hugpy checkout.
#
# /srv/hugpy is a real git repo (it has .git), so we update it IN PLACE: fetch
# origin/main and hard-reset onto it. This discards any uncommitted edits to
# tracked files — commit/push them with ./scripts/push-to-main.sh first if you
# want to keep them. Untracked/ignored runtime dirs (logs/, run/, backups/,
# miniforge3/, .env, …) are left untouched.
#
# Steps:
#   1. Fetch origin/main (retry on transient network failures).
#   2. Record the current revision for one-command rollback.
#   3. Hard-reset the working tree to origin/main.
#   4. Build the frontend (yarn && yarn build).
#   5. Restart the API service.
#
#   ./scripts/pull-from-main.sh
#   REPO=/some/path SERVICE=6092_hugpy_api ./scripts/pull-from-main.sh
#
set -euo pipefail

REPO="${REPO:-/srv/hugpy}"
BRANCH="${BRANCH:-main}"
# Name of the systemd-ish unit restarted at the end. The old abstractgpt deploy
# used 6092_abstractgpt_api; adjust to your real hugpy unit, or override with
#   SERVICE=<name> ./scripts/pull-from-main.sh
SERVICE="${SERVICE:-6092_hugpy_api}"

# Never block on an interactive credential prompt — fail fast with guidance
# instead of looping forever asking for a username/password.
export GIT_TERMINAL_PROMPT=0

# Use a specific (passwordless) deploy key if present, so the fetch works
# without a configured ~/.ssh/config and without an ssh-agent. Falls back to
# the default ssh resolution when the key file isn't there. Only applies to
# SSH remotes; HTTPS+token remotes ignore it.
DEPLOY_SSH_KEY="${DEPLOY_SSH_KEY:-/home/op/.ssh/github/githubssh_nopass}"
if [[ -z "${GIT_SSH_COMMAND:-}" ]]; then
  if [[ -f "$DEPLOY_SSH_KEY" ]]; then
    export GIT_SSH_COMMAND="ssh -i $DEPLOY_SSH_KEY -oBatchMode=yes -oIdentitiesOnly=yes"
  else
    export GIT_SSH_COMMAND="ssh -oBatchMode=yes"
  fi
fi

cd "$REPO"

# Must be a git repo.
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "error: $REPO is not a git repository" >&2
  exit 1
fi

# 1. Fetch latest main (retry on transient network failures).
echo "Fetching origin/$BRANCH…"
n=0
until git fetch origin "$BRANCH"; do
  n=$((n + 1))
  if (( n > 4 )); then
    echo "error: git fetch failed after retries." >&2
    cat >&2 <<EOF

Authentication likely failed. GitHub does NOT accept account passwords for git.
Pick one:
  • SSH (recommended): ensure 'ssh -T git@github.com' greets you, then re-run.
  • HTTPS + token: set the remote to an https URL with a Personal Access Token
    (repo scope), e.g.
      git -C $REPO remote set-url origin \\
        https://putkoff:<TOKEN>@github.com/AbstractEndeavors/hugpy.git
The username is always your personal account (putkoff), not the org.
EOF
    exit 1
  fi
  echo "fetch failed (attempt $n), retrying…"; sleep $((2 ** n))
done

OLD_REV="$(git rev-parse --short HEAD)"
NEW_REV="$(git rev-parse --short FETCH_HEAD)"

if [[ "$OLD_REV" == "$NEW_REV" ]]; then
  echo "Already at origin/$BRANCH ($NEW_REV) — nothing to deploy."
else
  # 2 & 3. Reset the working tree to the freshly fetched origin/main.
  echo "Deploying $OLD_REV -> $NEW_REV (hard reset to origin/$BRANCH)…"
  git reset --hard FETCH_HEAD
  echo "Rollback if needed:  git -C $REPO reset --hard $OLD_REV"
fi

# 4. Build the frontend.
echo "Building frontend…"
cd "$REPO/app"
yarn
yarn build

echo "✓ Deployed $BRANCH ($(git -C "$REPO" rev-parse --short HEAD))."

# 5. Restart the API service. This may stream the rolling log and block, so it
#    goes last — keep nothing after it.
echo "Restarting service $SERVICE…"
cd "$REPO"
restart_view_service "$SERVICE"
