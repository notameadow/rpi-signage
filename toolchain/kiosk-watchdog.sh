#!/usr/bin/env bash
# Kiosk watchdog — restarts Chromium if the renderer crashes.
# Runs as a user systemd service (signage-kiosk-watchdog.service).
#
# Checks every 30 seconds:
#   1. Is any Chromium renderer process alive?
#   2. Are there zombie Chromium processes? (sign of renderer crash)
# If unhealthy, kills all Chromium and relaunches via kiosk.sh.

CHECK_INTERVAL=30
KIOSK_SCRIPT="/home/dev/signage/toolchain/kiosk.sh"
PIDFILE="/tmp/signage-kiosk.pid"
LOG_TAG="kiosk-watchdog"

log() { logger -t "$LOG_TAG" "$*"; echo "$(date '+%F %T') $*"; }

is_healthy() {
    # Must have at least one Chromium renderer process
    if ! pgrep -f 'chromium.*--type=renderer' >/dev/null 2>&1; then
        log "UNHEALTHY: no Chromium renderer processes found"
        return 1
    fi

    # Check for zombie Chromium processes (state Z)
    local zombies
    zombies=$(ps -eo pid,stat,comm 2>/dev/null | awk '$2 ~ /Z/ && $3 ~ /chromium/ {print $1}')
    if [ -n "$zombies" ]; then
        log "UNHEALTHY: zombie Chromium processes: $zombies"
        return 1
    fi

    # Check Chromium memory usage — restart if renderer exceeds 800MB RSS
    local rss_kb
    rss_kb=$(ps -eo rss,args 2>/dev/null | awk '/chromium.*--type=renderer/ {sum += $1} END {print sum+0}')
    if [ "$rss_kb" -gt 819200 ] 2>/dev/null; then
        local rss_mb=$((rss_kb / 1024))
        log "UNHEALTHY: Chromium renderer using ${rss_mb}MB RSS (limit 800MB)"
        return 1
    fi

    return 0
}

restart_kiosk() {
    log "Killing all Chromium processes"
    pkill -9 -f chromium 2>/dev/null || true
    sleep 2
    # Clean up any remaining zombies
    pkill -9 -f chromium 2>/dev/null || true

    log "Relaunching kiosk"
    setsid "$KIOSK_SCRIPT" </dev/null >/dev/null 2>&1 &
    sleep 15  # give Chromium time to start + splash timer

    if is_healthy; then
        log "Kiosk recovered successfully"
    else
        log "WARNING: kiosk still unhealthy after restart"
    fi
}

# ── Main loop ─────────────────────────────────────────────────────────

log "Watchdog started (check every ${CHECK_INTERVAL}s)"

# Wait for initial kiosk launch (splash + redirect = ~15s)
sleep 20

while true; do
    if ! is_healthy; then
        restart_kiosk
    fi
    sleep "$CHECK_INTERVAL"
done
