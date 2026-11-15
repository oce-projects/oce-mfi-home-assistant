#!/bin/bash
# =============================================================================
# Home Assistant app (add-on) "Ubiquiti mFi Controller" - start script
# Version: 0.1.0 (full history in CHANGELOG.md)
#
# What it does:
#   1. reads the options from /data/options.json (written by Home Assistant);
#   2. on first start copies the factory configuration to /data/mfi;
#   3. starts "java -jar lib/ace.jar start" as user mfi;
#   4. on stop (SIGTERM) calls "ace.jar stop", which also stops MongoDB;
#   5. if the controller exits by itself it is restarted; after 5 exits in a
#      row, each less than 60 seconds after start, the script gives up.
#
# File changelog:
#   0.1.0 - 2026-11-15 - first version.
# =============================================================================
set -u

MFI_HOME=/usr/lib/mfi
DATA_DIR=/data/mfi
LOG_DIR=/data/logs
OPTIONS=/data/options.json

log() { echo "[mfi-run] $(date '+%Y-%m-%d %H:%M:%S') $*"; }

# --- Options ------------------------------------------------------------------
JAVA_MB=1024
if [ -f "$OPTIONS" ]; then
    v=$(jq -r '.java_max_memory_mb // empty' "$OPTIONS" 2>/dev/null || true)
    case "$v" in
        ''|*[!0-9]*) ;;
        *) JAVA_MB=$v ;;
    esac
fi

# --- Persistent data ------------------------------------------------------------
mkdir -p "$DATA_DIR" "$LOG_DIR"
if [ ! -f "$DATA_DIR/system.properties" ]; then
    log "first start: copying the factory configuration to $DATA_DIR"
    cp -a "$MFI_HOME/data-orig/." "$DATA_DIR/"
fi
chown -R mfi:mfi "$DATA_DIR" "$LOG_DIR"
touch "$LOG_DIR/server.log" && chown mfi:mfi "$LOG_DIR/server.log"

# Runs java as user mfi (jessie has neither runuser nor setpriv).
# start-stop-daemon execs java; started with "&" it runs in a subshell,
# so $! is the subshell, which ends when java ends.
# A non-existent --pidfile keeps "stop" from being refused as a duplicate.
as_mfi() {
    start-stop-daemon --start --quiet --chuid mfi:mfi --chdir "$MFI_HOME" \
        --pidfile /nonexistent-mfi.pid --startas /usr/bin/java -- "$@"
}

cd "$MFI_HOME" || exit 1

# --- Clean stop -------------------------------------------------------------------
STOPPING=0
stop_controller() {
    STOPPING=1
    log "stop requested: ace.jar stop"
    as_mfi -jar lib/ace.jar stop || true
}
trap stop_controller TERM INT

# The controller log also appears in the Home Assistant app log
tail -n 0 -F "$LOG_DIR/server.log" &
TAIL_PID=$!

# --- Run loop -------------------------------------------------------------------------
QUICK_EXITS=0
while :; do
    STARTED=$(date +%s)
    log "starting mFi Controller (Java max heap ${JAVA_MB} MB)"
    as_mfi "-Xmx${JAVA_MB}m" -jar lib/ace.jar start &
    JPID=$!

    # wait returns early when a signal arrives: keep waiting while java lives
    wait "$JPID"; RC=$?
    while kill -0 "$JPID" 2>/dev/null; do
        wait "$JPID"; RC=$?
    done

    if [ "$STOPPING" = 1 ]; then
        log "controller stopped (exit code $RC)"
        break
    fi

    UPTIME=$(( $(date +%s) - STARTED ))
    if [ "$UPTIME" -lt 60 ]; then
        QUICK_EXITS=$((QUICK_EXITS + 1))
    else
        QUICK_EXITS=0
    fi
    if [ "$QUICK_EXITS" -ge 5 ]; then
        log "the controller exited 5 times in a row within 60 seconds: giving up (exit code $RC)"
        kill "$TAIL_PID" 2>/dev/null
        exit 1
    fi
    log "the controller exited by itself after ${UPTIME} seconds (exit code $RC): restarting in 5 seconds"
    sleep 5
done

kill "$TAIL_PID" 2>/dev/null
exit 0
