#!/usr/bin/env bash
# Pin every bucket-3 (Bitmark-era) series to IPFS, byte-verified.
#
# For each series in the input CSV:
#   1. aws s3 sync  artworks/<sid>/ and previews/<sid>/  from the origin bucket
#   2. ipfs add -r --hidden --cid-version 1   (one CID per series directory;
#      --hidden is REQUIRED: zip-uploaded works contain dotfiles that add
#      silently skips by default — caught on Umwelt, 2026-08-03)
#   3. ipfs get the CID back and diff -r against the source (byte-exact or
#      it isn't a copy)
#   4. append to the manifest; delete the local copies (the blockstore keeps
#      the bytes)
#
# Resumable: series already in the manifest with a CID are skipped, so rerun
# after any interruption. Run this ON the pinning node (the ipfs repo that
# should hold the data long-term).
#
# Usage:
#   ./pin-works.sh <series_csv> <manifest_out.csv> [workdir]
# Env:
#   BUCKET       (default s3://feralfile-assets-livenet)
#   IPFS_BIN     (default ipfs)
#   IPFS_PATH    respected by ipfs as usual

set -euo pipefail

CSV="${1:?series csv (bitmark_series_media_*.csv)}"
MANIFEST="${2:?manifest output csv}"
WORKDIR="${3:-./pin-work}"
BUCKET="${BUCKET:-s3://feralfile-assets-livenet}"
IPFS_BIN="${IPFS_BIN:-ipfs}"

mkdir -p "$WORKDIR"
[[ -f "$MANIFEST" ]] || echo "series_id,cid,bytes,files,synced_at,verified" > "$MANIFEST"

total=0; done_n=0; skipped=0
for sid in $(tail -n +2 "$CSV" | cut -d, -f2 | sort -u); do
  total=$((total+1))
  if grep -q "^$sid," "$MANIFEST"; then skipped=$((skipped+1)); continue; fi

  src="$WORKDIR/$sid"
  rt="$WORKDIR/roundtrip-$sid"
  rm -rf "$src" "$rt"

  echo "[$sid] sync"
  aws s3 sync "$BUCKET/artworks/$sid/" "$src/artworks/" --only-show-errors
  aws s3 sync "$BUCKET/previews/$sid/" "$src/previews/" --only-show-errors
  files=$(find "$src" -type f | wc -l)
  bytes=$(du -sb "$src" | cut -f1)
  if [[ "$files" -eq 0 ]]; then
    echo "[$sid] ERROR: nothing synced" >&2
    exit 1
  fi

  echo "[$sid] add ($files files, $bytes bytes)"
  cid=$("$IPFS_BIN" add -r -Q --hidden --cid-version 1 "$src")

  echo "[$sid] verify"
  "$IPFS_BIN" get -o "$rt" "$cid" > /dev/null
  if ! diff -rq "$src" "$rt" > /dev/null; then
    echo "[$sid] ERROR: round-trip differs from source — NOT recorded" >&2
    rm -rf "$rt"
    exit 1
  fi

  "$IPFS_BIN" pin add "$cid" > /dev/null 2>&1 || true  # add already pins; belt and suspenders
  echo "$sid,$cid,$bytes,$files,$(date -u +%Y-%m-%dT%H:%M:%SZ),true" >> "$MANIFEST"
  done_n=$((done_n+1))
  echo "[$sid] OK $cid"
  rm -rf "$src" "$rt"
done

echo "pinned $done_n new, skipped $skipped already-done, of $total series"
