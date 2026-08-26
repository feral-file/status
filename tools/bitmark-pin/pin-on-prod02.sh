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
echo "peering with ff-pin-1: $(curl -s -X POST "$A/swarm/connect?arg=$FF_PIN_1")"

n=0; total=$(($(wc -l < "$MANIFEST") - 1))
tail -n +2 "$MANIFEST" | while IFS=, read -r sid cid bytes files rest; do
  n=$((n+1))
  t0=$(date +%s)
  # no timeout: a 20 GB series can take a while; progress=false keeps the JSON small
  res=$(curl -s -m 0 -X POST "$A/pin/add?arg=$cid&progress=false")
  printf '%s [%d/%d] %s %s %sB %ds %s\n' "$(date -u +%FT%TZ)" "$n" "$total" "$sid" "$cid" "$bytes" "$(( $(date +%s) - t0 ))" "$res" | tee -a pin.log
  case "$res" in *'"Pins"'*) ;; *) echo "  ^ not pinned — stopping; fix and rerun (already-pinned series are skipped instantly)" >&2; exit 1;; esac
done

echo "storage after: $(curl -s -X POST "$A/repo/stat?human=true")"
echo "recursive pins: $(curl -s -X POST "$A/pin/ls?type=recursive" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["Keys"]))')"
