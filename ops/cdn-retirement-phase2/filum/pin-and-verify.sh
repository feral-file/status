#!/usr/bin/env bash
# filum fix — add + pin the two rebuilt dirs on prod-02 and assert the CIDs match cids.csv.
# Operator: tunnel open first (in ff-deploy: make ipfs-port-forward ENV=prod HOST=prod-02).
# Idempotent: re-adding identical bytes yields the same CID; pins are a no-op if present.
set -euo pipefail
cd "$(dirname "$0")"
API="${API:-/ip4/127.0.0.1/tcp/5001}"
NEW_ART=$(awk -F, '/^artwork_dir/{print $3}' cids.csv)
NEW_BASE=$(awk -F, '/^base_dir/{print $3}' cids.csv)
[ -d build/art-new ] && [ -d build/base-new ] || { echo "build/ missing — run tools/metadata-regen/filum-build.py first"; exit 1; }
add() { ipfs --api "$API" add -r -Q --cid-version 0 --pin=true "$1"; }
got=$(add build/art-new);  [ "$got" = "$NEW_ART" ]  || { echo "artwork dir CID mismatch: $got != $NEW_ART"; exit 1; }
echo "✓ artwork dir pinned $NEW_ART"
got=$(add build/base-new); [ "$got" = "$NEW_BASE" ] || { echo "base dir CID mismatch: $got != $NEW_BASE"; exit 1; }
echo "✓ base dir pinned $NEW_BASE"
ipfs --api "$API" pin ls --type=recursive "$NEW_ART" "$NEW_BASE" >/dev/null && echo "✓ both recursive pins present"
# served through the public gateway (NoFetch: 200 == locally present)
for u in "https://ipfs.feralfile.com/ipfs/$NEW_ART/index.html" "https://ipfs.feralfile.com/ipfs/$NEW_ART/js/base.js" \
         "https://ipfs.feralfile.com/ipfs/$NEW_BASE/2439046679443273982118864381573244666655869184"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$u"); echo "$code $u"; [ "$code" = 200 ] || exit 1
done
# the served index.html must carry the 7 attributes
n=$(curl -s --max-time 60 "https://ipfs.feralfile.com/ipfs/$NEW_ART/index.html" | grep -o 'crossorigin="anonymous"' | wc -l | tr -d ' ')
[ "$n" = 7 ] || { echo "served index.html has $n crossorigin attrs, expected 7"; exit 1; }
echo "✓ served index.html carries 7× crossorigin=\"anonymous\""
echo "done — next: tools/update-token-uri/v4-base-uri.mjs preflight with v4-base-uri.config.filum.json"
