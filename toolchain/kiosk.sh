#!/usr/bin/env bash
# Signage kiosk launcher.
# Invoked by ~/.config/autostart/signage-kiosk.desktop on session start,
# or by the kiosk-watchdog when restarting after a crash.

WAYLAND_DISPLAY_VAL="${WAYLAND_DISPLAY:-wayland-0}"
XDG_RUNTIME_VAL="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
PIDFILE="/tmp/signage-kiosk.pid"

# Wait for Flask backend to be ready
until curl -s http://localhost:5000/ >/dev/null 2>&1; do
    sleep 2
done

# Force display on (in case compositor blanked it during boot)
WAYLAND_OUTPUT=$(
    WAYLAND_DISPLAY="$WAYLAND_DISPLAY_VAL" XDG_RUNTIME_DIR="$XDG_RUNTIME_VAL" \
    wlr-randr 2>/dev/null | awk 'NR==1{print $1}'
)
if [ -n "$WAYLAND_OUTPUT" ]; then
    WAYLAND_DISPLAY="$WAYLAND_DISPLAY_VAL" XDG_RUNTIME_DIR="$XDG_RUNTIME_VAL" \
        wlopm --on "$WAYLAND_OUTPUT" 2>/dev/null || true
    # Force 1920x1080 — Pi 4 GPU cannot render Chromium at 4K
    WAYLAND_DISPLAY="$WAYLAND_DISPLAY_VAL" XDG_RUNTIME_DIR="$XDG_RUNTIME_VAL" \
        wlr-randr --output "$WAYLAND_OUTPUT" --mode 1920x1080 2>/dev/null || true
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
    --disable-gpu-compositing
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
