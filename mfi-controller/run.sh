#!/bin/bash
# =============================================================================
# Home Assistant app (add-on) "Ubiquiti mFi Controller" - start script
# Full history in CHANGELOG.md
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
#   0.1.2 - 2026-11-15 - version line removed from the header.
#   0.2.0 - 2026-11-19 - compatibility recorder: options record_traffic and record_max_mb.
#   0.3.0 - 2026-11-19 - passive UDP capture (10001/3478): --udp-capture to the recorder.
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
RECORD_TRAFFIC=false
RECORD_MAX_MB=200
if [ -f "$OPTIONS" ]; then
    v=$(jq -r '.record_traffic // empty' "$OPTIONS" 2>/dev/null || true)
    if [ "$v" = "true" ]; then
        RECORD_TRAFFIC=true
    fi
    v=$(jq -r '.record_max_mb // empty' "$OPTIONS" 2>/dev/null || true)
    case "$v" in
        ''|*[!0-9]*) ;;
        *) RECORD_MAX_MB=$v ;;
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

# Compatibility recorder: the block between the two markers of system.properties
# is removed and, when record_traffic is on, written again. Two starts with the
# same options give the same file.
RECORDER_BEGIN="# mfi-recorder begin"
RECORDER_END="# mfi-recorder end"
write_recorder_properties() {
    local props="$DATA_DIR/system.properties"
    touch "$props" || return 1
    # Remove a previous block only when BOTH markers are present, so a file that
    # has only the begin marker (hand-edited or truncated) is not deleted to EOF.
    if grep -q "^# mfi-recorder begin$" "$props" && grep -q "^# mfi-recorder end$" "$props"; then
        sed -i "/^# mfi-recorder begin$/,/^# mfi-recorder end$/d" "$props" || return 1
    fi
    if [ "$RECORD_TRAFFIC" = true ]; then
        # Make sure the file ends with a newline, so the marker starts its own line.
        if [ -s "$props" ] && [ -n "$(tail -c1 "$props")" ]; then
            echo >> "$props" || return 1
        fi
        {
            echo "$RECORDER_BEGIN"
            echo "unifi.http.port=16080"
            echo "unifi.https.port=16443"
            echo "$RECORDER_END"
        } >> "$props" || return 1
        log "compatibility recorder on: the controller uses ports 16080 and 16443 inside the add-on"
    else
        log "compatibility recorder off"
    fi
    chown mfi:mfi "$props"
}
write_recorder_properties || { log "cannot write the recorder settings to $DATA_DIR/system.properties"; exit 1; }

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
RECORDER_PID=""
stop_recorder() {
    if [ -n "$RECORDER_PID" ]; then
        kill "$RECORDER_PID" 2>/dev/null
    fi
}
stop_controller() {
    STOPPING=1
    log "stop requested: ace.jar stop"
    as_mfi -jar lib/ace.jar stop || true
    stop_recorder
}
trap stop_controller TERM INT

# The controller log also appears in the Home Assistant app log
tail -n 0 -F "$LOG_DIR/server.log" &
TAIL_PID=$!

# --- Run loop -------------------------------------------------------------------------
# Returns 0 when 127.0.0.1:$1 accepts a connection
port_open() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

# Runs in the background, started after java. Creates the self-signed
# certificate once, waits up to 120 seconds for the controller ports, then
# keeps recorder.py running as user mfi (restarted 5 seconds after an exit).
start_recorder() {
    local dir=/data/recorder
    local out=/share/mfi-recordings
    local deadline https args rc

    mkdir -p "$dir" "$out" || { log "recorder not started: cannot create $dir or $out"; return 1; }
    if [ ! -f "$dir/cert.pem" ] || [ ! -f "$dir/key.pem" ]; then
        ( umask 077 && openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=mfi-recorder" \
            -keyout "$dir/key.pem" -out "$dir/cert.pem" ) \
            || { log "recorder not started: certificate creation failed"; return 1; }
    fi
    chmod 0600 "$dir/cert.pem" "$dir/key.pem" || return 1
    chown -R mfi:mfi "$dir" || return 1
    chown mfi:mfi "$out" || return 1
    chmod 0700 "$out" || return 1

    deadline=$(( $(date +%s) + 120 ))
    while ! { port_open 16080 && port_open 16443; } && [ "$(date +%s)" -lt "$deadline" ]; do
        sleep 2
    done
    port_open 16080 || log "recording of port 6080 unavailable: the controller did not open 16080"
    https=1
    if ! port_open 16443; then
        log "https recording unavailable: the controller did not move to 16443"
        https=0
    fi

    args=(--inform-listen 6080 --inform-target 16080 --out "$out" --max-mb "$RECORD_MAX_MB" --udp-capture)
    if [ "$https" = 1 ]; then
        args+=(--https-listen 6443 --https-target 16443 --cert "$dir/cert.pem" --key "$dir/key.pem")
    fi
    while :; do
        start-stop-daemon --start --quiet --chuid mfi:mfi --chdir / \
            --pidfile /nonexistent-recorder.pid --startas /usr/bin/python3 -- /recorder.py "${args[@]}"
        rc=$?
        log "recorder.py exited (exit code $rc): restarting in 5 seconds"
        sleep 5
    done
}

QUICK_EXITS=0
while :; do
    STARTED=$(date +%s)
    log "starting mFi Controller (Java max heap ${JAVA_MB} MB)"
    as_mfi "-Xmx${JAVA_MB}m" -jar lib/ace.jar start &
    JPID=$!
    if [ "$RECORD_TRAFFIC" = true ] && [ -z "$RECORDER_PID" ]; then
        start_recorder &
        RECORDER_PID=$!
    fi

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
        stop_recorder
        exit 1
    fi
    log "the controller exited by itself after ${UPTIME} seconds (exit code $RC): restarting in 5 seconds"
    sleep 5
done

stop_recorder
kill "$TAIL_PID" 2>/dev/null
exit 0
