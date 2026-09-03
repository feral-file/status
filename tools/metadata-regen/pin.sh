#!/usr/bin/env bash
# Add + pin every dir in plan.csv on prod-02 through the tunnel
# (make ipfs-port-forward ENV=prod HOST=prod-02 in ff-deploy), then verify each
# new <cid>/metadata.json through ipfs.bitmark.com (NoFetch → 200 means pinned).
#
#   ./pin.sh [plan.csv]            → result.csv (contract,edition,token_id,old_metadata_cid,new_metadata_cid,token_id_db,db_cid)
#                                    updates/<contract>.csv (edition,token_id,old_metadata_cid,new_metadata_cid — update-token-uri input)
# Idempotent: ipfs add of identical bytes yields the same CID; rows already in
# result.csv are skipped, so an interrupted run is resumed by re-running.
set -euo pipefail
cd "$(dirname "$0")"
PLAN=${1:-plan.csv}; A=${A:-http://127.0.0.1:5001/api/v0}; GW=${GW:-https://ipfs.bitmark.com/ipfs/}
curl -sf -X POST "$A/id" >/dev/null || { echo "kubo API not reachable at $A — open the tunnel"; exit 1; }
[ -f result.csv ] || echo "contract,edition,token_id,old_metadata_cid,new_metadata_cid,token_id_db,db_cid" > result.csv
mkdir -p updates
tail -n +2 "$PLAN" | while IFS=, read -r c ed tid oldcid _oa _oi _na _ni dir tdb dbcid _src _drop; do
  grep -q "^$c,$ed,$tid," result.csv && continue
  # wrap-with-directory → directory CID whose only entry is metadata.json (the tokenURI shape); cid-version 0 → Qm… like the originals
  newcid=$(curl -sf -X POST -F "file=@$dir/metadata.json;filename=metadata.json" \
    "$A/add?wrap-with-directory=true&cid-version=0&pin=true&quieter=true" \
    | python3 -c 'import json,sys
for l in sys.stdin:
    o=json.loads(l)
    if o.get("Name")=="": print(o["Hash"])')
  [ -n "$newcid" ] || { echo "add failed for $dir"; exit 1; }
  echo "$c,$ed,$tid,$oldcid,$newcid,${tdb:-$tid},${dbcid:-$oldcid}" | tee -a result.csv
done
# per-contract slices for tools/update-token-uri
tail -n +2 result.csv | while IFS=, read -r c ed tid old new _tdb _dbcid; do
  f="updates/$c.csv"; [ -f "$f" ] || echo "edition,token_id,old_metadata_cid,new_metadata_cid" > "$f"
  grep -q "^$ed,$tid," "$f" || echo "$ed,$tid,$old,$new" >> "$f"
done
echo; echo "gateway verify ($GW):"
fail=0
while IFS=, read -r c ed tid old new _tdb _dbcid; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "$GW$new/metadata.json")
  [ "$code" = 200 ] || { echo "  $c $tid $new → $code"; fail=$((fail+1)); }
done < <(tail -n +2 result.csv)
echo "$(($(wc -l < result.csv)-1)) pinned, $fail not servable"; [ "$fail" = 0 ]
