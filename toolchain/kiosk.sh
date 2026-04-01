#!/usr/bin/env bash
# Signage kiosk launcher.
# Invoked by ~/.config/autostart/signage-kiosk.desktop on session start.

WAYLAND_DISPLAY_VAL="${WAYLAND_DISPLAY:-wayland-0}"
XDG_RUNTIME_VAL="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

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

# Launch Chromium.
# Wrapped with systemd-inhibit to prevent idle/sleep while kiosk is running.
exec systemd-inhibit \
    --what=idle:sleep \
    --who=signage-kiosk \
    --why="Pub display" \
    --mode=block \
    env \
    WAYLAND_DISPLAY="$WAYLAND_DISPLAY_VAL" \
    XDG_RUNTIME_DIR="$XDG_RUNTIME_VAL" \
    chromium \
    --ozone-platform=wayland \
    --kiosk \
    --no-sandbox \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-restore-session-state \
    --autoplay-policy=no-user-gesture-required \
    --noerrdialogs \
    --disable-features=TranslateUI \
    --password-store=basic \
    http://localhost:5000/splash
