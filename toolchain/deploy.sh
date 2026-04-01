#!/usr/bin/env bash
# Deploy project to Pi via rsync.
#
# Usage:
#   RPi_HOST=dev@192.168.1.100 ./toolchain/deploy.sh
#   RPi_HOST=dev@192.168.1.100 RPi_SSH_KEY=~/.ssh/id_ed25519 ./toolchain/deploy.sh
#
set -euo pipefail

if [ -z "${RPi_HOST:-}" ]; then
    echo "Error: RPi_HOST is not set."
    echo "Usage: RPi_HOST=dev@<pi-address> ./toolchain/deploy.sh"
    exit 1
fi

RPi_SSH_KEY="${RPi_SSH_KEY:-$HOME/.ssh/id_ed25519}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_DIR="/home/dev/signage"

echo "→ Deploying to $RPi_HOST:$REMOTE_DIR"

rsync -av --delete \
  --exclude='.git/' \
  --exclude='data/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  --exclude='venv/' \
  --exclude='*.icloud' \
  --exclude='memory/' \
  --exclude='.claude/' \
  -e "ssh -i $RPi_SSH_KEY" \
  "$PROJECT_DIR/" \
  "$RPi_HOST:$REMOTE_DIR/"

echo "→ Done."
