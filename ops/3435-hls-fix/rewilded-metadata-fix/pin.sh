#!/usr/bin/env bash
# Add + pin the 50 replacement metadata directories on prod-02 via the tunnel
# (make ipfs-port-forward ENV=prod HOST=prod-02). Output: result.csv with
# edition,token_id,old_metadata_cid,new_metadata_cid — the input for
# updateArtworkEditionIPFSCid(tokenId, newCid).
set -euo pipefail
cd "$(dirname "$0")"
A=${A:-http://127.0.0.1:5001/api/v0}
echo "edition,token_id,old_metadata_cid,new_metadata_cid" > result.csv
tail -n +2 plan.csv | while IFS=, read -r ed cls tid oldcid rest; do
  dir=$(printf 'dirs/%03d' "$ed")
  # wrap-with-directory => directory CID whose only entry is metadata.json,
  # same shape as the existing tokenURI dirs. cid-version 0 => Qm… like the originals.
  newcid=$(curl -sf -X POST -F "file=@$dir/metadata.json;filename=metadata.json" \
    "$A/add?wrap-with-directory=true&cid-version=0&pin=true&quieter=true" \
    | python3 -c 'import json,sys
for l in sys.stdin:
    o=json.loads(l)
    if o.get("Name")=="": print(o["Hash"])')
  echo "$ed,$tid,$oldcid,$newcid" | tee -a result.csv
done
echo; echo "verify through the public gateway:"
tail -n +2 result.csv | while IFS=, read -r ed tid old new; do
  printf '%s %s ' "$ed" "$new"; curl -s -o /dev/null -w '%{http_code}\n' "https://ipfs.bitmark.com/ipfs/$new/metadata.json"
done
