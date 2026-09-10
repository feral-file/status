#!/usr/bin/env bash
# Pin the Bitmark-era series (the archive manifest's bitmark-era-series
# collection) on prod-02 so ipfs.feralfile.com serves them as a first-class
# source. Step 2 of feral-file#3435; decision 2026-08-26: ff-pin-1 stays the
# custody node, prod-02 mirrors it.
#
# Run from a machine with the IPFS tunnel open:
#   make ipfs-port-forward ENV=prod HOST=prod-02     (in ff-deploy)
#   ./pin-on-prod02.sh [pin_manifest.csv]
#
# Idempotent / resumable: `pin add` on an already-pinned CID returns at once.
# Each CID is fetched from the network; we connect to ff-pin-1 first because
# it holds every block and (as of 2026-08) does not announce them to the DHT.
# Progress goes to pin.log next to this script; rerun after any interruption.
set -euo pipefail
cd "$(dirname "$0")"
A=${A:-http://127.0.0.1:5001/api/v0}
MANIFEST=${1:-../../data/pin_manifest_2026-08-04.csv}
FF_PIN_1=${FF_PIN_1:-/ip4/167.172.246.239/tcp/4001/p2p/12D3KooWAdUhAD3u59bBRZrPAkEPLqtGt7Vcd9e2FVP4E1uEewyM}

curl -sf -X POST "$A/id" >/dev/null || { echo "no kubo API at $A — open the tunnel first" >&2; exit 1; }
echo "storage before: $(curl -s -X POST "$A/repo/stat?human=true")"
PEER=${FF_PIN_1##*/p2p/}
STALL_SECS=${STALL_SECS:-180}      # no bytes received for this long => reconnect and retry the series
# A long-lived connection to ff-pin-1 goes stale (2026-08-27, twice: connected,
# wantlist populated, zero bitswap exchange). Disconnecting by peer id drops
# every transport (the stale one is usually QUIC); reconnect over TCP.
repeer() {
  curl -s -X POST "$A/swarm/disconnect?arg=/p2p/$PEER" >/dev/null 2>&1 || true
  sleep 2
  curl -s -X POST "$A/swarm/connect?arg=$FF_PIN_1"
}
recv_bytes() { curl -s -X POST "$A/bitswap/stat" | python3 -c 'import json,sys;print(json.load(sys.stdin)["DataReceived"])'; }
echo "peering with ff-pin-1: $(repeer)"
first=$(sed -n 2p "$MANIFEST" | cut -d, -f2)
curl -sf -m 60 -X POST "$A/block/stat?arg=$first" >/dev/null || { echo "ff-pin-1 connected but not serving blocks (root of $first timed out) — see feral-file#3435 2026-08-27" >&2; exit 1; }
echo "block flow ok"

# pin one CID with a stall watchdog; returns 0 when kubo reports the pin
pin_with_watchdog() {
  local cid=$1 attempt=1
  while :; do
    local out; out=$(mktemp)
    curl -s -m 0 -X POST "$A/pin/add?arg=$cid&progress=false" > "$out" &
    local cpid=$! last=$(recv_bytes) idle=0
    while kill -0 "$cpid" 2>/dev/null; do
      sleep 30
      local now; now=$(recv_bytes)
      if [[ "$now" == "$last" ]]; then idle=$((idle+30)); else idle=0; last=$now; fi
      if (( idle >= STALL_SECS )); then
        echo "  stall: no bytes for ${idle}s on $cid (attempt $attempt) — re-peering" | tee -a pin.log >&2
        kill "$cpid" 2>/dev/null; wait "$cpid" 2>/dev/null; rm -f "$out"
        repeer >/dev/null; attempt=$((attempt+1)); continue 2
      fi
    done
    wait "$cpid"; local res; res=$(cat "$out"); rm -f "$out"
    case "$res" in *'"Pins"'*) echo "$res"; return 0;; esac
    echo "  pin add returned: ${res:-<empty>} (attempt $attempt) — re-peering" | tee -a pin.log >&2
    (( attempt >= 5 )) && return 1
    repeer >/dev/null; attempt=$((attempt+1)); sleep 10
  done
}

n=0; total=$(($(wc -l < "$MANIFEST") - 1))
tail -n +2 "$MANIFEST" | while IFS=, read -r sid cid bytes files rest; do
  n=$((n+1))
  t0=$(date +%s)
  if res=$(pin_with_watchdog "$cid"); then
    printf '%s [%d/%d] %s %s %sB %ds %s\n' "$(date -u +%FT%TZ)" "$n" "$total" "$sid" "$cid" "$bytes" "$(( $(date +%s) - t0 ))" "$res" | tee -a pin.log
  else
    echo "$(date -u +%FT%TZ) [$n/$total] $sid $cid FAILED after retries — stopping; rerun to resume" | tee -a pin.log >&2; exit 1
  fi
done

echo "storage after: $(curl -s -X POST "$A/repo/stat?human=true")"
echo "recursive pins: $(curl -s -X POST "$A/pin/ls?type=recursive" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["Keys"]))')"
