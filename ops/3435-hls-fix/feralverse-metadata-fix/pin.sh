#!/usr/bin/env bash
# Add + pin the 142 replacement TZIP-21 metadata files on prod-02 via the
# tunnel (make ipfs-port-forward ENV=prod HOST=prod-02). Tezos token_info
# points straight at the JSON file (no directory), so these are added as bare
# files, CIDv0 like the originals. Output: result.csv
#   token_id,old_metadata_cid,new_metadata_cid
set -euo pipefail
cd "$(dirname "$0")"
A=${A:-http://127.0.0.1:5001/api/v0}
echo "token_id,old_metadata_cid,new_metadata_cid" > result.csv
tail -n +2 plan.csv | while IFS=, read -r tid ed oldart oldcid file; do
  newcid=$(curl -sf -X POST -F "file=@$file" "$A/add?cid-version=0&pin=true&quieter=true" \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["Hash"])')
  echo "$tid,$oldcid,$newcid" | tee -a result.csv
done
echo; echo "verify through the public gateway:"
tail -n +2 result.csv | while IFS=, read -r tid old new; do
  printf '%s ' "$new"; curl -s -o /dev/null -w '%{http_code}\n' "https://ipfs.feralfile.com/ipfs/$new"
done
