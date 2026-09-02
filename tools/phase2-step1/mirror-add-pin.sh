#!/usr/bin/env bash
# Phase-2 Step 1b: mirror each CDN pin unit from the origin bucket and add it
# to prod-02 (pinned), recording unit -> dirCID for step 2's reference rows.
#
# Per unit (a row of step 0's cdn_dirs.csv):
#   1. aws s3 sync (dir) / aws s3 cp (bare file) from the origin bucket to a
#      local work dir
#   2. ipfs add -r --hidden --cid-version 0 -Q through the prod-02 tunnel —
#      the add pins by default; --cid-version 0 per the phase-2 doc (same as
#      the phase-1 metadata dirs), --hidden per pin_works.sh's rule
#   3. verify: fetch ONE sampled file via https://ipfs.feralfile.com AND
#      https://ipfs.io, byte-compare (cmp) against the local mirror.
#      ipfs.io may lag the reprovide cycle: retried, then recorded as
#      public_pending rather than failing the run (step 5's census is the
#      final acceptance).
#   4. append to the record CSV; delete the local mirror (KEEP=1 retains)
#
# prod-02 runs Gateway.NoFetch=true: everything referenced must be pinned
# (ff-deploy#28) — the add's default pin satisfies that for these dirs.
#
# Run from a machine with the IPFS tunnel open:
#   make ipfs-port-forward ENV=prod HOST=prod-02     (in ff-deploy)
#   BUCKET=<origin-bucket> ./mirror-add-pin.sh \
#       ops/cdn-retirement-phase2/step0/cdn_dirs.csv \
#       ops/cdn-retirement-phase2/step1/dir_cids.csv
#
# Env: BUCKET (required)   origin bucket name
#      API   (default /ip4/127.0.0.1/tcp/5001)  kubo API multiaddr (tunnel)
#      WORK  (default ./phase2-mirror)          local mirror scratch
#      KEEP=1                                    keep local mirrors
#      HEADROOM_STOP (default 90)                stop when repo% of StorageMax exceeds this
# Idempotent / resumable: units already in the record CSV are skipped.
set -euo pipefail
DIRS_CSV=${1:?cdn_dirs.csv from step 0}
RECORD=${2:?output record csv (dir_cids.csv)}
: "${BUCKET:?BUCKET env required}"
API=${API:-/ip4/127.0.0.1/tcp/5001}
WORK=${WORK:-./phase2-mirror}
CDN_PREFIX='https://cdn.feralfileassets.com/'
HEADROOM_STOP=${HEADROOM_STOP:-90}

ipfs --api "$API" id -f '<id>' >/dev/null || { echo "no kubo API at $API — open the tunnel first" >&2; exit 1; }
mkdir -p "$WORK" "$(dirname "$RECORD")"
[[ -f "$RECORD" ]] || echo "dir_or_file,s3_prefix,cid,n_files,bytes,gw_ff,gw_public,verified" > "$RECORD"

headroom_check() {
  ipfs --api "$API" repo stat | awk -v stop="$HEADROOM_STOP" '
    /^RepoSize/   {size=$2}
    /^StorageMax/ {max=$2}
    END {
      pct = 100 * size / max
      printf "repo %.0f GB / %.0f GB (%.0f%%)\n", size/1e9, max/1e9, pct
      exit (pct > stop) ? 1 : 0
    }'
}

in_record() { awk -F, -v u="$1" 'NR>1 && $1==u {f=1} END {exit !f}' "$RECORD"; }

fetch_ok() { # url localfile -> 0 if bytes match
  local tmp; tmp=$(mktemp)
  if curl -sfL --max-time 300 "$1" -o "$tmp" && cmp -s "$tmp" "$2"; then rm -f "$tmp"; return 0; fi
  rm -f "$tmp"; return 1
}

total=$(( $(wc -l < "$DIRS_CSV") - 1 )); i=0
tail -n +2 "$DIRS_CSV" | while IFS=, read -r unit _rest; do
  i=$((i+1))
  in_record "$unit" && { echo "[$i/$total] done, skip: $unit"; continue; }
  headroom_check || { echo "STOP: repo above ${HEADROOM_STOP}% of StorageMax — settle capacity first" >&2; exit 1; }

  key=${unit#"$CDN_PREFIX"}
  [[ "$key" != "$unit" ]] || { echo "[$i/$total] non-CDN host, manual: $unit" >&2; continue; }
  dst="$WORK/${key%/}"
  mkdir -p "$dst"
  if [[ "$unit" == */ ]]; then
    echo "[$i/$total] sync s3://$BUCKET/$key"
    aws s3 sync --only-show-errors "s3://$BUCKET/$key" "$dst/"
  else
    echo "[$i/$total] cp s3://$BUCKET/$key"
    aws s3 cp --only-show-errors "s3://$BUCKET/$key" "$dst/$(basename "$key")"
  fi
  n_files=$(find "$dst" -type f | wc -l | tr -d ' ')
  bytes=$(find "$dst" -type f -print0 | python3 -c 'import os,sys; print(sum(os.path.getsize(p) for p in sys.stdin.buffer.read().split(b"\0") if p))')
  [[ "$n_files" -gt 0 ]] || { echo "  EMPTY at origin — recorded, investigate" >&2; echo "$unit,$key,,0,0,,,empty_at_origin" >> "$RECORD"; continue; }

  if [[ "$unit" == */ ]]; then
    # directory unit: dir CID, references become ipfs://<cid>/<path>
    echo "  add -r --cid-version 0 ($n_files files, $bytes bytes)"
    cid=$(ipfs --api "$API" add -r --hidden --cid-version 0 -Q "$dst")
    sample=$(cd "$dst" && find . -type f | sed 's|^\./||' | sort | head -1)
    sample_local="$dst/$sample"; sample_path="/$sample"
  else
    # bare-file unit (shared thumbnail): the file's own CID, phase-1 HLS style
    echo "  add --cid-version 0 (1 file, $bytes bytes)"
    sample_local="$dst/$(basename "$key")"
    cid=$(ipfs --api "$API" add --hidden --cid-version 0 -Q "$sample_local")
    sample_path=""
  fi
  echo "  cid: $cid"

  gw_ff=fail; gw_pub=public_pending
  fetch_ok "https://ipfs.feralfile.com/ipfs/$cid$sample_path" "$sample_local" && gw_ff=ok
  for attempt in 1 2 3; do
    fetch_ok "https://ipfs.io/ipfs/$cid$sample_path" "$sample_local" && { gw_pub=ok; break; }
    sleep $((attempt * 20))
  done
  verified=$([[ "$gw_ff" == ok ]] && echo yes || echo NO)
  echo "$unit,$key,$cid,$n_files,$bytes,$gw_ff,$gw_pub,$verified" >> "$RECORD"
  echo "  ff-gateway: $gw_ff, public: $gw_pub"
  [[ "$gw_ff" == ok ]] || echo "  WARNING: ipfs.feralfile.com failed for $cid/$sample — investigate before step 2" >&2
  [[ -n "${KEEP:-}" ]] || rm -rf "$dst"
done
echo "DONE — record: $RECORD (public_pending entries: re-verify after the next reprovide cycle)"
