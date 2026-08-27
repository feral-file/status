#!/usr/bin/env bash
# Are the CIDs the DB's ipfs_reference rows point at PINNED on prod-02 (not just cached)?
# Input: a file of CIDs (one per line), e.g. from ops/3435-hls-fix/bitmark_existing_refs_probe_*.csv.
# Prints unpinned CIDs; with --pin, pins them (recursive). Tunnel required.
set -euo pipefail
A=${A:-http://127.0.0.1:5001/api/v0}
LIST=${1:?cid list file}; MODE=${2:-}
pinned=$(curl -s -X POST "$A/pin/ls?type=recursive" | python3 -c 'import json,sys;print("\n".join(json.load(sys.stdin)["Keys"]))')
missing=()
while read -r c; do [[ -z "$c" ]] && continue; grep -qx "$c" <<<"$pinned" || missing+=("$c"); done < "$LIST"
echo "$(wc -l < "$LIST") cids, ${#missing[@]} not pinned recursively"
for c in "${missing[@]}"; do
  if [[ "$MODE" == "--pin" ]]; then echo "pin $c $(curl -s -m 0 -X POST "$A/pin/add?arg=$c&progress=false")"; else echo "$c"; fi
done
