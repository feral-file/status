#!/usr/bin/env bash
# After pin-on-prod02.sh: confirm every series CID is (a) pinned recursively
# on prod-02 and (b) served by the public gateway. Read-only.
#   ./verify.sh [pin_manifest.csv]
set -euo pipefail
cd "$(dirname "$0")"
A=${A:-http://127.0.0.1:5001/api/v0}
MANIFEST=${1:-../../data/pin_manifest_2026-08-04.csv}
pinned=$(curl -s -X POST "$A/pin/ls?type=recursive" | python3 -c 'import json,sys;print("\n".join(json.load(sys.stdin)["Keys"]))')
ok=0; bad=0
tail -n +2 "$MANIFEST" | while IFS=, read -r sid cid rest; do
  p=$(grep -qx "$cid" <<<"$pinned" && echo pinned || echo NOT-PINNED)
  code=$(curl -s -o /dev/null -m 120 -w '%{http_code}' "https://ipfs.feralfile.com/ipfs/$cid/")
  printf '%s %s %s gateway=%s\n' "$sid" "$cid" "$p" "$code"
done | tee verify.log | awk '{ if ($3=="pinned" && $4=="gateway=200") ok++; else bad++ } END { printf "\n%d ok, %d not ok\n", ok, bad }'
