#!/usr/bin/env bash
# RPi Signage — installer.
#
# Fresh install (curl):
#   curl -sSL https://raw.githubusercontent.com/notameadow/rpi-signage/main/install.sh | bash
#
# Re-install / update (already cloned):
#   bash /home/dev/signage/install.sh
#
set -euo pipefail

INSTALL_DIR="/home/dev/signage"
REPO_URL="https://github.com/notameadow/rpi-signage.git"
UNIT_DIR="/etc/systemd/system"

# ── Clone repo if running via curl on a fresh system ─────────────────────────
if [ ! -f "$INSTALL_DIR/server.py" ]; then
    echo "=== Cloning rpi-signage ==="
    if ! command -v git &>/dev/null; then
        sudo apt-get update -q && sudo apt-get install -y git
    fi
    git clone "$REPO_URL" "$INSTALL_DIR"
    echo ""
fi

echo "=== RPi Signage Install ==="
echo ""

# ── 1. Python venv + requirements ────────────────────────────────────────────
echo "→ Python venv..."
cd "$INSTALL_DIR"
if [ ! -d venv ]; then
    python3 -m venv venv
fi
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt
mkdir -p data/media data/usb_cache
echo "  OK"

# ── 2. signage-app systemd service ───────────────────────────────────────────
echo "→ signage-app service..."
sudo cp "$INSTALL_DIR/systemd/signage-app.service" "$UNIT_DIR/"
sudo systemctl daemon-reload
sudo systemctl enable signage-app
sudo systemctl restart signage-app
sleep 3
if systemctl is-active --quiet signage-app; then
    echo "  OK (running)"
else
    echo "  ERROR: signage-app failed to start — last logs:"
    journalctl -u signage-app -n 20 --no-pager
    exit 1
fi

# ── 3. Kiosk autostart (XDG, picked up by lxsession-xdg-autostart) ──────────
echo "→ Kiosk autostart..."
chmod +x "$INSTALL_DIR/toolchain/kiosk.sh"
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/signage-kiosk.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Signage Kiosk
Exec=$INSTALL_DIR/toolchain/kiosk.sh
X-GNOME-Autostart-enabled=true
Hidden=false
NoDisplay=false
EOF
echo "  OK (~/.config/autostart/signage-kiosk.desktop)"

# ── 3a. Kiosk output assignment (matters on Pi 5 only) ──────────────────────
# /etc/default/signage-kiosk lets the operator pin which HDMI port shows
# signage and which is force-off'd. Pi 4 ignores it (single HDMI; kiosk.sh
# auto-falls-back to whatever's present).
if [ ! -f /etc/default/signage-kiosk ]; then
    sudo install -m 0644 -o root -g root \
        "$INSTALL_DIR/systemd/signage-kiosk.env.example" /etc/default/signage-kiosk
    echo "  /etc/default/signage-kiosk created (defaults: SIGNAGE_OUTPUT=HDMI-A-1, BLANK_OUTPUT=HDMI-A-2)"
fi

# ── 4. Cursor: set to 1px so it is effectively invisible ────────────────────
echo "→ Cursor size..."
ENV_FILE="$HOME/.config/labwc/environment"
if ! grep -q "XCURSOR_SIZE" "$ENV_FILE" 2>/dev/null; then
    echo "XCURSOR_SIZE=1" >> "$ENV_FILE"
    echo "  OK (appended to $ENV_FILE)"
else
    echo "  already set"
fi

# ── 5. Suppress gnome-keyring — mask user service + hide XDG autostart entries
# gnome-keyring shows a "create keyring" dialog on autologin if no default
# collection exists. For a kiosk we don't need it at all — mask everything.
echo "→ Suppressing gnome-keyring..."
# Remove PAM lines if previously patched
sudo sed -i '/pam_gnome_keyring/d' /etc/pam.d/lightdm-autologin 2>/dev/null || true
# Mask systemd user units
systemctl --user mask gnome-keyring-daemon.service gnome-keyring-daemon.socket 2>/dev/null || true
# Override system XDG autostart .desktop files with hidden=true
for f in gnome-keyring-pkcs11 gnome-keyring-secrets gnome-keyring-ssh; do
    if [ ! -f "$HOME/.config/autostart/$f.desktop" ] || ! grep -q "Hidden=true" "$HOME/.config/autostart/$f.desktop" 2>/dev/null; then
        printf '[Desktop Entry]\nHidden=true\n' > "$HOME/.config/autostart/$f.desktop"
    fi
done
echo "  OK (masked + hidden)"

# ── 6. Suppress pcmanfm autorun dialog ──────────────────────────────────────
# pcmanfm --desktop shows a "Removable media inserted" dialog on USB insertion.
# Disable it while keeping automount active (USB monitor depends on udisks2).
echo "→ Suppressing pcmanfm autorun dialog..."
mkdir -p "$HOME/.config/pcmanfm/default"
cat > "$HOME/.config/pcmanfm/default/pcmanfm.conf" << 'EOF'
[volume]
mount_on_startup=1
mount_removable=1
autorun=0
close_on_unmount=1
EOF
echo "  OK"

# ── 7. WiFi power save: disable to prevent brcmfmac disassociation/crash ────
# Pi 4 BCM4345 firmware aggressively sleeps WiFi, causing periodic disconnects
# and occasional hard hangs. powersave=2 means "disable".
echo "→ Disabling WiFi power save..."
NM_CONF="/etc/NetworkManager/NetworkManager.conf"
if ! grep -q 'wifi\.powersave' "$NM_CONF" 2>/dev/null; then
    sudo tee -a "$NM_CONF" > /dev/null << 'NMEOF'

[connection]
wifi.powersave=2
NMEOF
    echo "  OK (added to $NM_CONF)"
else
    echo "  already configured"
fi

# ── 8. Captive portal: disable NetworkManager connectivity check ────────────
# Prevents browser popup on captive-portal networks from interrupting kiosk.
echo "→ Disabling captive portal check..."
if ! grep -q '\[connectivity\]' "$NM_CONF" 2>/dev/null; then
    sudo tee -a "$NM_CONF" > /dev/null << 'NMEOF'

[connectivity]
enabled=false
NMEOF
    echo "  OK (added to $NM_CONF)"
else
    echo "  already configured"
fi
sudo systemctl reload NetworkManager 2>/dev/null || true

# ── 9. Persistent journal: override Debian volatile default ─────────────────
# Debian ships 40-rpi-volatile-storage.conf — override with higher-numbered
# drop-in so crash logs survive reboots. Capped at 50M to protect SD card.
echo "→ Enabling persistent journal..."
JOURNAL_DROPIN="/etc/systemd/journald.conf.d/50-persistent.conf"
if [ ! -f "$JOURNAL_DROPIN" ]; then
    sudo mkdir -p /etc/systemd/journald.conf.d
    sudo tee "$JOURNAL_DROPIN" > /dev/null << 'JEOF'
[Journal]
Storage=persistent
SystemMaxUse=50M
JEOF
    sudo mkdir -p "/var/log/journal/$(cat /etc/machine-id)"
    sudo chown root:systemd-journal "/var/log/journal/$(cat /etc/machine-id)"
    sudo chmod 2755 "/var/log/journal/$(cat /etc/machine-id)"
    sudo systemctl restart systemd-journald
    echo "  OK"
else
    echo "  already configured"
fi

# ── 10. Kiosk watchdog — restarts Chromium on renderer crash ────────────────
echo "→ Kiosk watchdog service..."
chmod +x "$INSTALL_DIR/toolchain/kiosk-watchdog.sh"
mkdir -p "$HOME/.config/systemd/user"
cp "$INSTALL_DIR/systemd/signage-kiosk-watchdog.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable signage-kiosk-watchdog
systemctl --user restart signage-kiosk-watchdog 2>/dev/null || true
echo "  OK"

# ── 11. Screen blanking: xset via Xwayland (belt-and-suspenders) ────────────
echo "→ Screen blanking (xset)..."
DISPLAY=:0 xset s off 2>/dev/null && echo "  xset s off: OK" || echo "  xset s off: skipped"
DISPLAY=:0 xset s noblank 2>/dev/null || true

# ── 12. Off-box backup (data → operator-defined destination) ────────────────
# Daily timer + on-demand run from the admin UI. Destination is configured
# in /etc/signage-backup.env (NOT in this repo — operator-specific). Path
# is hostname-namespaced so old/new Pis can coexist during a transition.
# SSH key path is settable via REMOTE_KEY in that env file.
echo "→ Off-box backup..."
chmod +x "$INSTALL_DIR/toolchain/pi-backup.sh"
sudo install -m 0755 "$INSTALL_DIR/toolchain/pi-backup.sh" /usr/local/bin/signage-backup.sh
sudo cp "$INSTALL_DIR/systemd/signage-backup.service" "$UNIT_DIR/"
sudo cp "$INSTALL_DIR/systemd/signage-backup.timer"   "$UNIT_DIR/"

# Install the env example once, root:dev 0640. Group-readable by dev so the
# Flask app (running as dev) can source it when spawning the script directly;
# other users still can't read it.
if [ ! -f /etc/signage-backup.env ]; then
    sudo install -m 0640 -o root -g dev \
        "$INSTALL_DIR/systemd/signage-backup.env.example" /etc/signage-backup.env
    echo "  ⚠  /etc/signage-backup.env created from example — fill in REMOTE_USER,"
    echo "     REMOTE_HOST, REMOTE_PORT, REMOTE_BASE before backups will succeed:"
    echo "       sudo \$EDITOR /etc/signage-backup.env"
else
    # Ensure perms are correct on existing installs (root:dev 0640).
    sudo chown root:dev /etc/signage-backup.env
    sudo chmod 0640 /etc/signage-backup.env
fi

sudo systemctl daemon-reload
sudo systemctl enable --now signage-backup.timer
echo "  OK (timer enabled; check /etc/signage-backup.env for destination)"

echo ""
echo "=== Install complete ==="
echo ""
IP=$(hostname -I | awk '{print $1}')
echo "  Admin UI : http://${IP}:5000/admin"
echo "  Username : admin  (default)"
echo "  Password : signage  (default — change this!)"
echo ""
echo "  Set credentials via systemd drop-in:"
echo "    sudo systemctl edit signage-app"
echo "  Then add:"
echo "    [Service]"
echo "    Environment=SIGNAGE_USER=admin"
echo "    Environment=SIGNAGE_PASS=yourpassword"
echo ""
echo "  Reboot to start kiosk automatically:"
echo "    sudo reboot"
