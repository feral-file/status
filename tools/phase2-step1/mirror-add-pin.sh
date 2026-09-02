#!/usr/bin/env bash
# Phase-2 Step 1b: mirror each CDN pin unit from the origin bucket and add it
# to prod-02 (pinned), recording unit -> CID for step 2's reference rows.
#
# curl-only against the kubo HTTP API through the tunnel (same convention as
# tools/bitmark-pin/pin-on-prod02.sh) — no local ipfs binary needed.
# Directory units are built file-by-file in MFS (each file its own small
# POST /add?to-files=…, resumable — a dropped connection costs one file, not
# the unit; see add_dir below). A built-in self-test exercises the exact
# same path on a tiny nested dir and byte-compares it through the gateway
# BEFORE any real unit.
#
# Per unit (a row of step 0's cdn_dirs.csv):
#   1. aws s3 sync (dir) / aws s3 cp (bare file) from the origin bucket
#   2. POST /api/v0/add?cid-version=0&hidden=true — pins by default
#      (required under prod-02's Gateway.NoFetch, ff-deploy#28);
#      dir unit -> dir CID, bare file -> its own file CID (phase-1 HLS style)
#   3. verify: fetch ONE sampled file via https://ipfs.feralfile.com AND
#      https://ipfs.io, byte-compare against the local mirror. ipfs.io may
#      lag the reprovide cycle: retried, then recorded public_pending (step
#      5's census is the final acceptance).
#   4. append to the record CSV; delete the local mirror (KEEP=1 retains)
#
# Run from a machine with the IPFS tunnel open:
#   make ipfs-port-forward ENV=prod HOST=prod-02     (in ff-deploy)
#   BUCKET=<origin-bucket> ./mirror-add-pin.sh \
#       ops/cdn-retirement-phase2/step0/cdn_dirs.csv \
#       ops/cdn-retirement-phase2/step1/dir_cids.csv
#
# Env: BUCKET (required)   origin bucket name
#      A     (default http://127.0.0.1:5001/api/v0)  kubo API base (tunnel)
#      WORK  (default ./phase2-mirror)               local mirror scratch
#      KEEP=1                                        keep local mirrors
#      HEADROOM_STOP (default 90)   stop when repo% of StorageMax exceeds this
# Idempotent / resumable: units already in the record CSV are skipped.
set -euo pipefail
# forensic traps: two silent deaths at the same spot (after a long add, during
# pin/verify) with no message — record WHAT terminated us and the last command.
trap 'rc=$?; [[ $rc -ne 0 ]] && echo "[trap] EXIT code=$rc last-command: $BASH_COMMAND" >&2' EXIT
for sig in HUP INT TERM PIPE; do trap "echo \"[trap] received SIG$sig — last-command: \$BASH_COMMAND\" >&2; exit 1" $sig; done
DIRS_CSV=${1:?cdn_dirs.csv from step 0}
RECORD=${2:?output record csv (dir_cids.csv)}
: "${BUCKET:?BUCKET env required}"
A=${A:-http://127.0.0.1:5001/api/v0}
WORK=${WORK:-./phase2-mirror}
CDN_PREFIX='https://cdn.feralfileassets.com/'
HEADROOM_STOP=${HEADROOM_STOP:-90}

command -v aws >/dev/null || { echo "aws CLI not installed" >&2; exit 1; }
curl -sf -X POST "$A/id" >/dev/null || { echo "no kubo API at $A — open the tunnel first (make ipfs-port-forward ENV=prod HOST=prod-02)" >&2; exit 1; }
mkdir -p "$WORK" "$(dirname "$RECORD")"
[[ -f "$RECORD" ]] || echo "dir_or_file,s3_prefix,cid,n_files,bytes,gw_ff,gw_public,verified" > "$RECORD"

headroom_check() {
  curl -s -X POST "$A/repo/stat" | python3 -c "
import json, sys
s = json.load(sys.stdin)
pct = 100 * s['RepoSize'] / s['StorageMax']
print(f\"repo {s['RepoSize']/1e9:.0f} GB / {s['StorageMax']/1e9:.0f} GB ({pct:.0f}%)\")
sys.exit(1 if pct > $HEADROOM_STOP else 0)"
}

in_record() { awk -F, -v u="$1" 'NR>1 && $1==u {f=1} END {exit !f}' "$RECORD"; }

# add_dir <local-dir> <s3-key-prefix> [pin] -> prints root dir CID
#
# Resumable per-file MFS build — NOT one giant multipart POST (the first
# crystalline attempt died silently ~30 GB into a single 45k-part POST; a
# dropped tunnel connection loses everything and can't resume). Instead:
# each file is its own small POST /add?to-files=<MFS path>&pin=false, the
# finished MFS directory's stat Hash is the dir CID, one pin/add pins it
# recursively, and the MFS path is removed. Rerunning skips files already
# in MFS (files/stat), so an interruption costs at most one file.
MFS_ROOT=/phase2-mirror
enc() { python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"; }

add_dir() {
  local dst=$1 keypfx=$2 pin=${3:-true}
  local mfs="$MFS_ROOT/${keypfx%/}" cid
  # batched upload (mfs-batch-add.py): ~200 files per POST — the per-file
  # loop was latency-bound (2 round-trips × ~0.3 s × 45k files ≈ 8 h).
  cid=$(python3 "$(cd "$(dirname "$0")" && pwd)/mfs-batch-add.py" "$dst" "$mfs" --api "${A%/api/v0}") || return 1
  [[ -n "$cid" ]] || return 1
  [[ "$pin" == true ]] && { curl -sf -X POST "$A/pin/add?arg=$cid" >/dev/null || { echo "  pin/add failed for $cid" >&2; return 1; }; }
  # staging is NOT removed here: the caller cleans it only after the record
  # row is written, so a death in the verify window leaves the CID findable
  # in MFS (2026-09-03 incident: pin done, record lost, CID unrecoverable).
  echo "$cid"
}

mfs_clean() { curl -sf -X POST "$A/files/rm?arg=$(enc "$MFS_ROOT/${1%/}")&recursive=true" >/dev/null 2>&1 || true; }

# add_file <local-file> -> prints file CID
add_file() {
  curl -sS -X POST -F "file=@\"$1\"" "$A/add?cid-version=0&hidden=true&progress=false&quieter=true" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['Hash'])"
}

fetch_ok() { # url localfile -> 0 if bytes match
  local tmp; tmp=$(mktemp)
  if curl -sfL --max-time 300 "$1" -o "$tmp" && cmp -s "$tmp" "$2"; then rm -f "$tmp"; return 0; fi
  rm -f "$tmp"; return 1
}

# --- self-test: prove the multipart dir shape end-to-end before real units --
selftest() {
  local d="$WORK/.selftest"
  rm -rf "$d"; mkdir -p "$d/sub"
  echo "phase2 selftest a" > "$d/a.txt"
  echo "phase2 selftest b" > "$d/sub/b.txt"
  local cid; cid=$(add_dir "$d" ".selftest" false)   # pin=false: cache only, tiny
  [[ -n "$cid" ]] || { echo "self-test: add returned no root CID" >&2; return 1; }
  fetch_ok "https://ipfs.feralfile.com/ipfs/$cid/sub/b.txt" "$d/sub/b.txt" \
    || { echo "self-test: gateway fetch/byte-compare failed for $cid/sub/b.txt" >&2; return 1; }
  echo "self-test ok (dir CID $cid, nested file verified via gateway)"
  mfs_clean ".selftest"; rm -rf "$d"
}
selftest || exit 1

total=$(( $(wc -l < "$DIRS_CSV") - 1 )); i=0
# read the unit list on fd 3 so nothing inside the loop can eat the list's stdin
while IFS=, read -r -u3 unit _rest; do
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
    echo "  add dir ($n_files files, $bytes bytes)"
    cid=$(add_dir "$dst" "$key") || { echo "ERROR: add_dir failed on $unit — rerun the same command to resume" >&2; exit 1; }
    sample=$(cd "$dst" && find . -type f | sed 's|^\./||' | LC_ALL=C sort | head -1)
    sample_local="$dst/$sample"; sample_path="/$sample"
  else
    echo "  add file ($bytes bytes)"
    sample_local="$dst/$(basename "$key")"
    cid=$(add_file "$sample_local") || { echo "ERROR: add_file failed on $unit — rerun to resume" >&2; exit 1; }
    sample_path=""
  fi
  [[ -n "$cid" ]] || { echo "  ERROR: add returned no CID for $unit" >&2; exit 1; }
  echo "  cid: $cid"

  gw_ff=fail; gw_pub=public_pending
  fetch_ok "https://ipfs.feralfile.com/ipfs/$cid$sample_path" "$sample_local" && gw_ff=ok
  for attempt in 1 2 3; do
    fetch_ok "https://ipfs.io/ipfs/$cid$sample_path" "$sample_local" && { gw_pub=ok; break; }
    sleep $((attempt * 20))
  done
  verified=$([[ "$gw_ff" == ok ]] && echo yes || echo NO)
  echo "$unit,$key,$cid,$n_files,$bytes,$gw_ff,$gw_pub,$verified" >> "$RECORD"
  [[ "$unit" == */ ]] && mfs_clean "$key"
  echo "  ff-gateway: $gw_ff, public: $gw_pub"
  [[ "$gw_ff" == ok ]] || echo "  WARNING: ipfs.feralfile.com failed for $cid$sample_path — investigate before step 2" >&2
  [[ -n "${KEEP:-}" ]] || rm -rf "$dst"
done 3< <(tail -n +2 "$DIRS_CSV")
echo "DONE — record: $RECORD (public_pending entries: re-verify after the next reprovide cycle)"
