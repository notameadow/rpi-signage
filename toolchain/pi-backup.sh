#!/usr/bin/env bash
# Signage off-box backup → operator-supplied destination.
#
# Configuration is read from environment variables, normally injected via
# /etc/signage-backup.env (sourced by the systemd unit). The repo ships an
# example at systemd/signage-backup.env.example. Required vars:
#
#   REMOTE_USER  REMOTE_HOST  REMOTE_PORT  REMOTE_BASE
#
# Optional: REMOTE_KEY (default: /home/dev/.ssh/id_ed25519_backup),
#           RETAIN_DAYS (default: 30),
#           DATA_DIR    (default: /home/dev/signage/data).
#
# Layout on the destination:
#   $REMOTE_BASE/<hostname>/YYYY-MM-DD/<data contents>
#
# Each day's snapshot hard-links unchanged files against the previous day
# via rsync --link-dest. Hostname-namespaced from the start so a Pi-to-Pi
# transition can run old + new in parallel without clobbering snapshots.
#
# Progress: rsync runs with --info=progress2 and a parser writes
# $PROGRESS_FILE atomically on each progress line. The Flask app reads it
# for the live progress bar.
#
# Mutex: a non-blocking flock on $LOCK_FILE prevents the timer-driven and
# operator-triggered runs from colliding.

set -euo pipefail

: "${REMOTE_USER:?REMOTE_USER is unset (see /etc/signage-backup.env)}"
: "${REMOTE_HOST:?REMOTE_HOST is unset (see /etc/signage-backup.env)}"
: "${REMOTE_PORT:?REMOTE_PORT is unset (see /etc/signage-backup.env)}"
: "${REMOTE_BASE:?REMOTE_BASE is unset (see /etc/signage-backup.env)}"
REMOTE_KEY="${REMOTE_KEY:-/home/dev/.ssh/id_ed25519_backup}"
RETAIN_DAYS="${RETAIN_DAYS:-30}"

DATA_DIR="${DATA_DIR:-/home/dev/signage/data}"
STATE_FILE="${STATE_FILE:-$DATA_DIR/backup-state.json}"
LOCK_FILE="${LOCK_FILE:-$DATA_DIR/.backup.lock}"
PROGRESS_FILE="${PROGRESS_FILE:-$DATA_DIR/.backup-progress}"

HOSTNAME_SHORT="$(hostname -s)"
TODAY="$(date +%F)"
YESTERDAY="$(date -d 'yesterday' +%F)"
REMOTE_HOST_BASE="$REMOTE_BASE/$HOSTNAME_SHORT"

SSH_OPTS=(-i "$REMOTE_KEY" -p "$REMOTE_PORT" -o StrictHostKeyChecking=yes -o BatchMode=yes)

log() { echo "$(date -Iseconds)  $*"; }

# Acquire mutex (non-blocking). If held, exit without touching state.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "another backup in progress — exiting"
    exit 0
fi

write_state() {
    # $1=running (true/false), $2=last_status, $3=last_error, $4=last_size_bytes, $5=last_duration_s
    local running="$1" status="$2" err="$3" size="$4" duration="$5"
    local started_at="${STARTED_AT:-null}"
    [ "$started_at" != "null" ] && started_at="\"$started_at\""
    local err_field="null"
    [ -n "$err" ] && err_field="\"$(echo "$err" | sed 's/"/\\"/g')\""
    cat > "$STATE_FILE.tmp" <<EOF
{
  "running": $running,
  "started_at": $started_at,
  "last_run_at": "$(date -Iseconds)",
  "last_status": "$status",
  "last_error": $err_field,
  "last_size_bytes": $size,
  "last_duration_s": $duration,
  "host": "$HOSTNAME_SHORT"
}
EOF
    mv "$STATE_FILE.tmp" "$STATE_FILE"
}

write_progress() {
    # $1=bytes_done $2=pct $3=rate $4=eta
    cat > "$PROGRESS_FILE.tmp" <<EOF
{"bytes_done":$1,"pct":$2,"rate":"$3","eta":"$4"}
EOF
    mv "$PROGRESS_FILE.tmp" "$PROGRESS_FILE"
}

clear_progress() { rm -f "$PROGRESS_FILE" "$PROGRESS_FILE.tmp" 2>/dev/null || true; }

STARTED_AT="$(date -Iseconds)"
START_EPOCH="$(date +%s)"

if [ -f "$STATE_FILE" ]; then
    PREV_STATUS="$(grep -o '"last_status": "[^"]*"' "$STATE_FILE" | sed 's/.*: "\(.*\)"/\1/' || echo unknown)"
    PREV_SIZE="$(grep -o '"last_size_bytes": [0-9]*' "$STATE_FILE" | awk '{print $2}' || echo 0)"
    PREV_DURATION="$(grep -o '"last_duration_s": [0-9.]*' "$STATE_FILE" | awk '{print $2}' || echo 0)"
else
    PREV_STATUS="never"; PREV_SIZE=0; PREV_DURATION=0
fi
write_state "true" "$PREV_STATUS" "" "$PREV_SIZE" "$PREV_DURATION"
clear_progress

cleanup_error() {
    local err_msg="$1"
    local elapsed=$(( $(date +%s) - START_EPOCH ))
    write_state "false" "error" "$err_msg" 0 "$elapsed"
    clear_progress
    log "FAILED: $err_msg"
    exit 1
}
trap 'cleanup_error "interrupted"' INT TERM

log "backup start → host=${REMOTE_HOST_BASE} today=${TODAY}"

if [ ! -d "$DATA_DIR" ]; then
    cleanup_error "data dir missing: $DATA_DIR"
fi

if ! ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$REMOTE_HOST" "mkdir -p \"$REMOTE_HOST_BASE/$TODAY\"" 2>/tmp/signage-backup-err; then
    cleanup_error "ssh mkdir failed: $(cat /tmp/signage-backup-err)"
fi

# rsync with progress2; pipe through a parser that writes $PROGRESS_FILE.
# pipefail makes rsync's exit propagate even though it's the LHS of the pipe.
set -o pipefail
RSYNC_ERR=/tmp/signage-backup-rsync-err
: > "$RSYNC_ERR"

if ! stdbuf -oL rsync -a --delete --info=progress2 --outbuf=L \
        -e "ssh ${SSH_OPTS[*]}" \
        --link-dest="$REMOTE_HOST_BASE/$YESTERDAY/" \
        "$DATA_DIR/" \
        "$REMOTE_USER@$REMOTE_HOST:$REMOTE_HOST_BASE/$TODAY/" 2>>"$RSYNC_ERR" \
    | stdbuf -oL tr '\r' '\n' \
    | while IFS= read -r line; do
        # progress2 lines look like: "    1,234,567  42%  10.50MB/s    0:00:30  (xfr#…)"
        if [[ "$line" =~ ^[[:space:]]*([0-9,]+)[[:space:]]+([0-9]+)%[[:space:]]+([^[:space:]]+)[[:space:]]+([0-9:]+) ]]; then
            bytes="${BASH_REMATCH[1]//,/}"
            pct="${BASH_REMATCH[2]}"
            rate="${BASH_REMATCH[3]}"
            eta="${BASH_REMATCH[4]}"
            write_progress "$bytes" "$pct" "$rate" "$eta"
        fi
    done; then
    cleanup_error "rsync failed: $(tail -1 "$RSYNC_ERR")"
fi
log "synced signage data"
clear_progress

# Prune old snapshots on the destination (per-host).
ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$REMOTE_HOST" \
    "cd \"$REMOTE_HOST_BASE\" 2>/dev/null && ls -d ????-??-?? 2>/dev/null | sort -r | awk 'NR>$RETAIN_DAYS' | xargs -r rm -rf" || true

SIZE_BYTES=$(ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$REMOTE_HOST" \
    "du -sb \"$REMOTE_HOST_BASE/$TODAY\" 2>/dev/null | awk '{print \$1}'" || echo 0)
SIZE_BYTES="${SIZE_BYTES:-0}"

ELAPSED=$(( $(date +%s) - START_EPOCH ))
write_state "false" "ok" "" "$SIZE_BYTES" "$ELAPSED"

log "backup complete (size=${SIZE_BYTES}B duration=${ELAPSED}s)"
