#!/usr/bin/env bash
# Signage off-box backup → droplet.
#
# Layout on the droplet:
#   /srv/backup/REDACTED/<hostname>/YYYY-MM-DD/<data contents>
#
# Each day's snapshot hard-links unchanged files against the previous day
# via rsync --link-dest, so a month of history costs barely more than one.
# Hostname-namespaced from the start so a Pi-to-Pi transition (old + new
# both alive) does not race for the same date directory.
#
# Writes a state file at $STATE_FILE before and after the run. The Flask
# app reads it for the admin "Backup" section.
#
# Mutex: a non-blocking flock on $LOCK_FILE prevents the timer-driven and
# operator-triggered runs from colliding. Second runner exits silently.

set -euo pipefail

REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_HOST="${REMOTE_HOST:-REDACTED.IP}"
REMOTE_PORT="${REMOTE_PORT:-REDACTED_PORT}"
REMOTE_KEY="${REMOTE_KEY:-/home/dev/.ssh/id_ed25519_backup}"
REMOTE_BASE="${REMOTE_BASE:-/srv/backup/REDACTED}"
RETAIN_DAYS="${RETAIN_DAYS:-30}"

DATA_DIR="${DATA_DIR:-/home/dev/signage/data}"
STATE_FILE="${STATE_FILE:-$DATA_DIR/backup-state.json}"
LOCK_FILE="${LOCK_FILE:-$DATA_DIR/.backup.lock}"

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
  "host": "$HOSTNAME_SHORT",
  "remote": "$REMOTE_USER@$REMOTE_HOST:$REMOTE_HOST_BASE"
}
EOF
    mv "$STATE_FILE.tmp" "$STATE_FILE"
}

STARTED_AT="$(date -Iseconds)"
START_EPOCH="$(date +%s)"

# Mark running. Preserve previous last_* fields by reading existing state if present.
if [ -f "$STATE_FILE" ]; then
    PREV_STATUS="$(grep -o '"last_status": "[^"]*"' "$STATE_FILE" | sed 's/.*: "\(.*\)"/\1/' || echo unknown)"
    PREV_SIZE="$(grep -o '"last_size_bytes": [0-9]*' "$STATE_FILE" | awk '{print $2}' || echo 0)"
    PREV_DURATION="$(grep -o '"last_duration_s": [0-9.]*' "$STATE_FILE" | awk '{print $2}' || echo 0)"
else
    PREV_STATUS="never"; PREV_SIZE=0; PREV_DURATION=0
fi
write_state "true" "$PREV_STATUS" "" "$PREV_SIZE" "$PREV_DURATION"

cleanup_error() {
    local err_msg="$1"
    local elapsed=$(( $(date +%s) - START_EPOCH ))
    write_state "false" "error" "$err_msg" 0 "$elapsed"
    log "FAILED: $err_msg"
    exit 1
}
trap 'cleanup_error "interrupted"' INT TERM

log "backup start → ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PORT} base=${REMOTE_HOST_BASE} today=${TODAY}"

if [ ! -d "$DATA_DIR" ]; then
    cleanup_error "data dir missing: $DATA_DIR"
fi

if ! ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$REMOTE_HOST" "mkdir -p \"$REMOTE_HOST_BASE/$TODAY\"" 2>/tmp/signage-backup-err; then
    cleanup_error "ssh mkdir failed: $(cat /tmp/signage-backup-err)"
fi

if ! rsync -a --delete \
        -e "ssh ${SSH_OPTS[*]}" \
        --link-dest="$REMOTE_HOST_BASE/$YESTERDAY/" \
        "$DATA_DIR/" \
        "$REMOTE_USER@$REMOTE_HOST:$REMOTE_HOST_BASE/$TODAY/" 2>/tmp/signage-backup-err; then
    cleanup_error "rsync failed: $(cat /tmp/signage-backup-err | tail -1)"
fi
log "synced signage data"

# Prune old snapshots on the droplet (per-host).
ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$REMOTE_HOST" \
    "cd \"$REMOTE_HOST_BASE\" 2>/dev/null && ls -d ????-??-?? 2>/dev/null | sort -r | awk 'NR>$RETAIN_DAYS' | xargs -r rm -rf" || true

# Measure today's snapshot size on the droplet (apparent, not link-dedup'd).
SIZE_BYTES=$(ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$REMOTE_HOST" \
    "du -sb \"$REMOTE_HOST_BASE/$TODAY\" 2>/dev/null | awk '{print \$1}'" || echo 0)
SIZE_BYTES="${SIZE_BYTES:-0}"

ELAPSED=$(( $(date +%s) - START_EPOCH ))
write_state "false" "ok" "" "$SIZE_BYTES" "$ELAPSED"

log "backup complete (size=${SIZE_BYTES}B duration=${ELAPSED}s)"
