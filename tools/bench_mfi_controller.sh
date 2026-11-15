#!/bin/bash
# =============================================================================
# bench_mfi_controller.sh - test bench for the "mfi-controller" app (add-on)
# Version: 1.0.0
#
# Runs on any amd64 Linux host with Docker. It never touches Home Assistant.
# Every command appends what it measures to $BENCH/bench.log.
# NOT a unit test: it needs Docker and the internet (AGENTS.md rule 4), so it
# is run by a human, never by the offline test suite.
#
# Usage:
#   bench_mfi_controller.sh build <mfi-controller folder>
#   bench_mfi_controller.sh start      test container, measures 6443 and 6080
#   bench_mfi_controller.sh wizard     creates a TEST administrator (random password)
#   bench_mfi_controller.sh client     login and device list with mficlient 0.5.0
#                                      (the library of the Home Assistant "mfi" integration)
#   bench_mfi_controller.sh restart    docker stop + start, timings and persistence
#   bench_mfi_controller.sh restore <file.unf>
#                                      THROWAWAY container with --network none:
#                                      restores a backup and counts documents per
#                                      collection (numbers only: no content is printed)
#   bench_mfi_controller.sh clean      removes containers, test image and $BENCH
#
# Changelog:
#   1.0.0 - 2026-11-15 - English port of the first working bench (wizard, login,
#           mficlient, restart, restore with POST /api/v1.0/cmd/system
#           {"cmd":"restore"}, data deleted through a container because the
#           files belong to uid 500 and the host user cannot remove them).
# =============================================================================
set -u

IMG=local/mfi-controller:bench
CNT=mfi-bench
BENCH=${BENCH:-/tmp/mfi-bench}
P_HTTPS=16443
P_HTTP=16080
LOG=$BENCH/bench.log
mkdir -p "$BENCH"; chmod 700 "$BENCH"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
now() { date +%s.%N; }
dt()  { awk -v a="$1" -v b="$2" 'BEGIN{printf "%.1f", b-a}'; }

# Waits until a URL answers with any HTTP code (not 000).
# $1 = label, $2 = curl command printing the code, $3 = max seconds
wait_http() {
    local t0 code i; t0=$(now)
    for i in $(seq 1 "$3"); do
        code=$(eval "$2" 2>/dev/null)
        if [ -n "$code" ] && [ "$code" != "000" ]; then
            log "$1: answers HTTP $code after $(dt "$t0" "$(now)") s"
            return 0
        fi
        sleep 1
    done
    log "$1: NO answer within $3 s"
    return 1
}

listening_ports() {  # $1 = container
    docker exec "$1" sh -c "awk 'NR>1 && \$4==\"0A\" {split(\$2,a,\":\"); print a[2]}' /proc/net/tcp /proc/net/tcp6" \
        | sort -u | while read -r h; do printf '%d ' "0x$h"; done; echo
}

inside_metrics() {  # $1 = container
    log "versions: $(docker exec "$1" sh -c 'java -version 2>&1 | head -1; mongod --version | head -1' | tr '\n' ' ')"
    log "TCP ports listening in the container: $(listening_ports "$1")"
    log "processes:"; docker exec "$1" ps -eo user,pid,rss,args | cut -c1-220 | tee -a "$LOG"
    log "space used in /data: $(docker exec "$1" du -sh /data | cut -f1)"
    log "memory: $(docker stats --no-stream --format '{{.MemUsage}}' "$1")"
}

# Files in /data belong to user mfi (uid 500): the host user cannot delete
# them. They are deleted with a throwaway container without network.
delete_data() {  # $1 = subfolder of $BENCH
    docker run --rm --network none -v "$BENCH:/p" --entrypoint rm "$IMG" -rf "/p/$1"
    if [ -e "$BENCH/$1" ]; then log "ERROR: $BENCH/$1 not deleted"; return 1; fi
}

make_credentials() {  # user and random password; never printed
    if [ ! -f "$BENCH/cred.env" ]; then
        umask 077
        echo "MFI_USER=bench" > "$BENCH/cred.env"
        echo "MFI_PASS=$(head -c 18 /dev/urandom | base64 | tr -d '/+=')" >> "$BENCH/cred.env"
    fi
}

# First-run wizard through the API, as the page wizard.jsp does.
# $1 = command prefix (empty = host, "docker exec X" = inside the container), $2 = base URL
wizard_api() {
    local run="$1" base="$2" u p J
    u=$(grep MFI_USER "$BENCH/cred.env" | cut -d= -f2); p=$(grep MFI_PASS "$BENCH/cred.env" | cut -d= -f2)
    printf '{"name":"%s","lang":"en_US","x_password":"%s"}' "$u" "$p" > "$BENCH/admin.json"; chmod 600 "$BENCH/admin.json"
    if [ -n "$run" ]; then docker cp "$BENCH/admin.json" "${run##* }:/tmp/admin.json"; J=/tmp/admin.json; else J=$BENCH/admin.json; fi
    $run curl -sk "$base/api/v1.0/add/admin" --data-urlencode "json@$J" -o /dev/null -w "add/admin HTTP %{http_code}\n" | tee -a "$LOG"
    $run curl -sk "$base/api/v1.0/cmd/devmgr" --data-urlencode 'json={"cmd":"adopt","macs":[]}' -o /dev/null -w "adopt HTTP %{http_code}\n" | tee -a "$LOG"
    $run curl -sk "$base/api/v1.0/set/setting/country" --data-urlencode 'json={"code":"380"}' -o /dev/null -w "country HTTP %{http_code}\n" | tee -a "$LOG"
    $run curl -sk "$base/api/v1.0/cmd/system" --data-urlencode 'json={"cmd":"set-installed"}' -w " set-installed HTTP %{http_code}\n" | tee -a "$LOG"
    if [ -n "$run" ]; then $run rm -f /tmp/admin.json; fi
    rm -f "$BENCH/admin.json"
}

# Login with the /login form, as mficlient does. Prints the final URL (/manage = success).
login_api() {  # $1 = command prefix, $2 = base URL, $3 = cookie jar
    local run="$1" base="$2" jar="$3" u p PW
    u=$(grep MFI_USER "$BENCH/cred.env" | cut -d= -f2); p=$(grep MFI_PASS "$BENCH/cred.env" | cut -d= -f2)
    printf '%s' "$p" > "$BENCH/pw"; chmod 600 "$BENCH/pw"
    if [ -n "$run" ]; then docker cp "$BENCH/pw" "${run##* }:/tmp/pw"; PW=/tmp/pw; else PW=$BENCH/pw; fi
    $run curl -sk -c "$jar" -b "$jar" "$base/" -o /dev/null
    $run curl -sk -L -c "$jar" -b "$jar" "$base/login" --data-urlencode "username=$u" \
        --data-urlencode "password@$PW" --data-urlencode "login=Login" -o /dev/null -w "login HTTP %{http_code} -> %{url_effective}\n" | tee -a "$LOG"
    if [ -n "$run" ]; then $run rm -f /tmp/pw; fi
    rm -f "$BENCH/pw"
}

case "${1:-}" in
build)
    SRC=${2:?mfi-controller folder}
    rm -rf "$BENCH/src"; cp -r "$SRC" "$BENCH/src"
    log "build from $SRC (sha256 of Dockerfile $(sha256sum "$BENCH/src/Dockerfile" | cut -c1-16))"
    t0=$(now)
    if nice -n 19 docker build --build-arg BUILD_VERSION="$(grep -m1 '^version:' "$BENCH/src/config.yaml" | tr -dc '0-9.')" \
            -t "$IMG" "$BENCH/src" > "$BENCH/build.log" 2>&1; then
        log "build OK in $(dt "$t0" "$(now)") s; image $(docker image inspect -f '{{.Size}}' "$IMG") bytes"
        grep -E 'mFi.unix.zip: OK' "$BENCH/build.log" | tee -a "$LOG"
        docker image inspect -f '{{json .Config.Labels}}' "$IMG" | tee -a "$LOG"
    else
        log "build FAILED after $(dt "$t0" "$(now)") s"; tail -30 "$BENCH/build.log" | tee -a "$LOG"; exit 1
    fi
    ;;
start)
    docker rm -f "$CNT" >/dev/null 2>&1
    delete_data data || exit 1; mkdir -p "$BENCH/data"
    echo '{"java_max_memory_mb": 1024}' > "$BENCH/data/options.json"
    docker run -d --name "$CNT" --init --memory 3g \
        -v "$BENCH/data:/data" -p 127.0.0.1:$P_HTTP:6080 -p 127.0.0.1:$P_HTTPS:6443 "$IMG" >/dev/null || exit 1
    log "container started"
    wait_http "6443 (HTTPS)" "curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1:$P_HTTPS/" 300
    wait_http "6080 (inform)" "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$P_HTTP/inform" 120
    log "start page: $(curl -sk -o /dev/null -w '%{http_code} -> %{redirect_url}' https://127.0.0.1:$P_HTTPS/)"
    log "POST /status: $(curl -sk -X POST https://127.0.0.1:$P_HTTPS/status | head -c 300)"
    log "TLS as seen by OpenSSL $(openssl version | cut -d' ' -f2):"
    echo | openssl s_client -connect 127.0.0.1:$P_HTTPS 2>/dev/null | grep -E 'Protocol|Cipher is|Server public key|Peer signature type' | tee -a "$LOG"
    echo | openssl s_client -connect 127.0.0.1:$P_HTTPS 2>/dev/null | openssl x509 -noout -subject -enddate -text 2>/dev/null \
        | grep -E 'subject=|notAfter|Signature Algorithm|Public-Key' | sort -u | tee -a "$LOG"
    sleep 20; inside_metrics "$CNT"
    ;;
wizard)
    make_credentials
    wizard_api "" "https://127.0.0.1:$P_HTTPS"
    login_api "" "https://127.0.0.1:$P_HTTPS" "$BENCH/jar"
    ;;
client)
    cat > "$BENCH/client.py" <<'EOF'
import os, socket, ssl, warnings
warnings.filterwarnings("ignore")
from mficlient.client import MFiClient
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
with socket.create_connection(("127.0.0.1", 16443)) as s:
    with ctx.wrap_socket(s) as t:
        print("python", ssl.OPENSSL_VERSION, "->", t.version(), t.cipher()[0])
c = MFiClient("127.0.0.1", os.environ["MFI_USER"], os.environ["MFI_PASS"], port=16443, use_tls=True, verify=False)
print("mficlient login OK; devices:", len(c.get_devices()))
EOF
    docker run --rm --network host --env-file "$BENCH/cred.env" -v "$BENCH/client.py:/client.py:ro" python:3.13-slim \
        sh -c "pip install -q --root-user-action=ignore mficlient==0.5.0 >/dev/null 2>&1; python /client.py" 2>&1 | tee -a "$LOG"
    ;;
restart)
    t0=$(now); docker stop -t 120 "$CNT" >/dev/null
    log "docker stop: $(dt "$t0" "$(now)") s, exit code $(docker inspect -f '{{.State.ExitCode}}' "$CNT")"
    docker logs "$CNT" 2>&1 | grep -E '\[mfi-run\]' | tail -4 | tee -a "$LOG"
    docker start "$CNT" >/dev/null
    wait_http "6443 after restart" "curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1:$P_HTTPS/" 300
    login_api "" "https://127.0.0.1:$P_HTTPS" "$BENCH/jar2"
    ;;
restore)
    UNF=${2:?file .unf}
    R=mfi-throwaway
    docker rm -f "$R" >/dev/null 2>&1; delete_data rdata || exit 1; mkdir -p "$BENCH/rdata"
    make_credentials
    log "=== restore of $(basename "$UNF") ($(stat -c %s "$UNF") bytes) in a throwaway container, network: none"
    docker run -d --name "$R" --init --memory 3g --network none -v "$BENCH/rdata:/data" "$IMG" >/dev/null || exit 1
    B=https://127.0.0.1:6443
    wait_http "throwaway 6443" "docker exec $R curl -sk -o /dev/null -w '%{http_code}' $B/" 300
    sleep 10
    wizard_api "docker exec $R" "$B"
    login_api "docker exec $R" "$B" /tmp/jar
    docker cp "$UNF" "$R:/tmp/backup.unf"
    t0=$(now)
    docker exec "$R" curl -sk -c /tmp/jar -b /tmp/jar "$B/upload/backup" -H 'X-Requested-With: XMLHttpRequest' \
        -H 'X-File-Name: backup.unf' -H "X-File-Size: $(stat -c %s "$UNF")" -H 'Content-Type: multipart/form-data' \
        --data-binary @/tmp/backup.unf -o /tmp/up.json -w "upload/backup HTTP %{http_code}\n" | tee -a "$LOG"
    log "upload answer (meta): $(docker exec "$R" sh -c 'jq -c "{rc: .meta.rc, msg: .meta.msg, version: .meta.version}" /tmp/up.json 2>/dev/null || head -c 200 /tmp/up.json')"
    log "upload: $(dt "$t0" "$(now)") s"
    t0=$(now)
    # as waiting.jsp does: the page /op/restore then sends $.jcmd('system','restore')
    docker exec "$R" curl -sk -c /tmp/jar -b /tmp/jar "$B/op/restore" -o /dev/null -w "op/restore HTTP %{http_code}\n" | tee -a "$LOG"
    docker exec "$R" curl -sk -m 30 -c /tmp/jar -b /tmp/jar "$B/api/v1.0/cmd/system" --data-urlencode 'json={"cmd":"restore"}' \
        -w " cmd/system restore HTTP %{http_code}\n" | tee -a "$LOG"
    DOWN=""; for i in $(seq 1 900); do
        up=$(docker exec "$R" sh -c "curl -sk -m 5 -X POST $B/status | jq -r '.meta.up // empty'" 2>/dev/null)
        if [ -z "$DOWN" ] && [ "$up" != "true" ]; then DOWN=1; log "server down after $(dt "$t0" "$(now)") s"; fi
        if [ -n "$DOWN" ] && [ "$up" = "true" ]; then log "server up again after $(dt "$t0" "$(now)") s"; break; fi
        if [ "$(docker inspect -f '{{.State.Running}}' "$R")" != "true" ]; then log "the container STOPPED"; break; fi
        sleep 1
    done
    docker logs "$R" 2>&1 | grep -E '\[mfi-run\]' | tee -a "$LOG"
    sleep 15
    MP=$(docker exec "$R" ps -o args= -C mongod | grep -o -- '--port [0-9]*' | cut -d' ' -f2)
    log "internal MongoDB on port $MP; documents per collection (numbers only):"
    docker exec "$R" mongo --quiet --port "$MP" ace --eval 'db.getCollectionNames().forEach(function(c){print("  "+c+" "+db[c].count())})' | tee -a "$LOG"
    inside_metrics "$R"
    docker rm -f "$R" >/dev/null
    delete_data rdata && log "throwaway container and its data DELETED (rdata folder absent)"
    ;;
clean)
    docker rm -f "$CNT" mfi-throwaway >/dev/null 2>&1
    delete_data data; delete_data rdata
    docker rmi "$IMG" >/dev/null 2>&1
    rm -rf "$BENCH"
    echo "clean"
    ;;
*)
    sed -n 2,26p "$0"; exit 2
    ;;
esac
