#!/usr/bin/env bash
# Signage kiosk launcher.
# Invoked by ~/.config/autostart/signage-kiosk.desktop on session start,
# or by the kiosk-watchdog when restarting after a crash.
#
# Output assignment (Pi 5 has two HDMI ports; Pi 4 has only one):
#   SIGNAGE_OUTPUT  the wlr-randr output that should display the slideshow
#                   (default: HDMI-A-1 if present; otherwise the first
#                   non-NOOP output enumerated by wlr-randr).
#   BLANK_OUTPUT    a comma-separated list of outputs to force off — the
#                   Pi 5's second HDMI is reserved for a future playout
#                   subsystem and must not mirror or echo signage content.
#                   (default: HDMI-A-2.) Outputs in this list that don't
#                   exist on the running hardware (e.g. on a Pi 4) are
#                   skipped silently.
# Override either via /etc/default/signage-kiosk or by editing the
# autostart .desktop file's Exec= line.

WAYLAND_DISPLAY_VAL="${WAYLAND_DISPLAY:-wayland-0}"
XDG_RUNTIME_VAL="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
PIDFILE="/tmp/signage-kiosk.pid"

# Operator-overridable defaults (file is optional).
[ -r /etc/default/signage-kiosk ] && . /etc/default/signage-kiosk

SIGNAGE_OUTPUT="${SIGNAGE_OUTPUT:-HDMI-A-1}"
BLANK_OUTPUT="${BLANK_OUTPUT:-HDMI-A-2}"

run_wlr() {
    WAYLAND_DISPLAY="$WAYLAND_DISPLAY_VAL" XDG_RUNTIME_DIR="$XDG_RUNTIME_VAL" \
        wlr-randr "$@" 2>/dev/null
}

# Wait for Flask backend to be ready
until curl -s http://localhost:5000/ >/dev/null 2>&1; do
    sleep 2
done

# Enumerate present outputs.
PRESENT_OUTPUTS=$(run_wlr | awk '/^[A-Z]/ && $1 !~ /^NOOP/ {print $1}')

# Resolve SIGNAGE_OUTPUT: if the configured one isn't present, fall back to
# the first present non-NOOP output. This lets a fresh Pi 4 image (single
# HDMI named e.g. HDMI-A-2) work without operator intervention.
if ! grep -qx "$SIGNAGE_OUTPUT" <<<"$PRESENT_OUTPUTS"; then
    FIRST_PRESENT=$(echo "$PRESENT_OUTPUTS" | head -n1)
    if [ -n "$FIRST_PRESENT" ]; then
        echo "[kiosk] $SIGNAGE_OUTPUT not present; falling back to $FIRST_PRESENT" >&2
        SIGNAGE_OUTPUT="$FIRST_PRESENT"
    fi
fi

# Force-off any output named in BLANK_OUTPUT that actually exists.
IFS=',' read -ra _blanks <<<"$BLANK_OUTPUT"
for out in "${_blanks[@]}"; do
    out="${out// /}"
    [ -z "$out" ] && continue
    [ "$out" = "$SIGNAGE_OUTPUT" ] && continue   # never blank the active one
    if grep -qx "$out" <<<"$PRESENT_OUTPUTS"; then
        run_wlr --output "$out" --off || true
        echo "[kiosk] forced off: $out" >&2
    fi
done

# Bring up the signage output.
if grep -qx "$SIGNAGE_OUTPUT" <<<"$PRESENT_OUTPUTS"; then
    WAYLAND_DISPLAY="$WAYLAND_DISPLAY_VAL" XDG_RUNTIME_DIR="$XDG_RUNTIME_VAL" \
        wlopm --on "$SIGNAGE_OUTPUT" 2>/dev/null || true
    # Force 1920x1080. Pi 4's GPU can't drive Chromium at 4K and Pi 5
    # behaves better at 1080p too given the AVR scaler in the path.
    run_wlr --output "$SIGNAGE_OUTPUT" --on --mode 1920x1080 || true
    echo "[kiosk] signage on: $SIGNAGE_OUTPUT @ 1920x1080" >&2
else
    echo "[kiosk] no usable output yet (PRESENT_OUTPUTS empty) — Chromium will follow whatever appears" >&2
fi

CHROMIUM_ARGS=(
    --ozone-platform=wayland
    --kiosk
    --no-sandbox
    --disable-infobars
    --disable-session-crashed-bubble
    --disable-restore-session-state
    --autoplay-policy=no-user-gesture-required
    --noerrdialogs
    --disable-features=TranslateUI
    --password-store=basic
    http://localhost:5000/splash
)

# Try systemd-inhibit to prevent idle/sleep; fall back to bare launch
# (inhibit requires polkit access, which SSH sessions don't have).
if systemd-inhibit --what=idle:sleep --who=signage-kiosk \
       --why="Pub display" --mode=block true 2>/dev/null; then
    WAYLAND_DISPLAY="$WAYLAND_DISPLAY_VAL" \
    XDG_RUNTIME_DIR="$XDG_RUNTIME_VAL" \
    systemd-inhibit --what=idle:sleep --who=signage-kiosk \
        --why="Pub display" --mode=block \
        chromium "${CHROMIUM_ARGS[@]}" &
else
    WAYLAND_DISPLAY="$WAYLAND_DISPLAY_VAL" \
    XDG_RUNTIME_DIR="$XDG_RUNTIME_VAL" \
    chromium "${CHROMIUM_ARGS[@]}" &
fi

KIOSK_PID=$!
echo "$KIOSK_PID" > "$PIDFILE"
wait "$KIOSK_PID"
rm -f "$PIDFILE"
