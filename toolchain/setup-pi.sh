#!/usr/bin/env bash
# First-time setup on the Pi. Run after first deploy:
#   ssh -i ~/.ssh/id_ed25519 dev@<pi-address> 'bash /home/dev/signage/toolchain/setup-pi.sh'
set -euo pipefail

REMOTE_DIR="/home/dev/signage"
cd "$REMOTE_DIR"

echo "→ Creating venv"
if [ ! -d venv ]; then
    python3 -m venv venv
fi

echo "→ Installing requirements"
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt

echo "→ Creating data directories"
mkdir -p data/media data/usb_cache

echo "→ Setup complete. Run server with:"
echo "   cd $REMOTE_DIR && venv/bin/python server.py"
