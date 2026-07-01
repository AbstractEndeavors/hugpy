#!/usr/bin/env bash
# Install the hugpy GPU worker as a systemd service.
#
#   sudo ./install.sh
#
# Idempotent: re-running updates the unit and reloads systemd. It will NOT
# overwrite an existing /etc/hugpy-worker.env (your config is safe).
set -euo pipefail

UNIT_SRC="$(cd "$(dirname "$0")" && pwd)/hugpy-worker.service"
ENV_SRC="$(cd "$(dirname "$0")" && pwd)/hugpy-worker.env.example"

UNIT_DST="/etc/systemd/system/hugpy-worker.service"
ENV_DST="/etc/hugpy-worker.env"
SVC_USER="${SVC_USER:-hugpy}"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (sudo)." >&2
  exit 1
fi

# 1. Service account (no login, owns the state dir).
if ! id -u "$SVC_USER" >/dev/null 2>&1; then
  echo "Creating service user '$SVC_USER'…"
  useradd --system --no-create-home --shell /usr/sbin/nologin "$SVC_USER"
fi

# 2. Env file — install the example once; never clobber an edited config.
if [[ -f "$ENV_DST" ]]; then
  echo "Keeping existing $ENV_DST (edit it to reconfigure)."
else
  echo "Installing $ENV_DST — EDIT IT before starting (set WORKER_CENTRAL_URL)."
  install -m 0640 -o root -g "$SVC_USER" "$ENV_SRC" "$ENV_DST"
fi

# 3. Unit file.
echo "Installing $UNIT_DST…"
install -m 0644 "$UNIT_SRC" "$UNIT_DST"

# 4. Activate.
systemctl daemon-reload
systemctl enable hugpy-worker.service

cat <<EOF

Installed. Next:
  1. Edit /etc/hugpy-worker.env  (at minimum set WORKER_CENTRAL_URL)
  2. Confirm 'python3 -m hugpy.worker_agent --help' works for user $SVC_USER
     (or point ExecStart in the unit at your venv's python).
  3. Start it:    sudo systemctl start hugpy-worker
     Watch logs:  journalctl -u hugpy-worker -f

The worker will then appear in the console's GPU Workers panel.
EOF
