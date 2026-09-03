#!/usr/bin/env bash
# Pin individual files to the archival node, byte-verified.
#
# The directory-oriented sibling is pin-works.sh; this one is for the case that
# recurs under "hosting follows stewardship": a handful of loose files for work
# Feral File published or stewards, which should not be left on a public
# gateway. Same rules as pin-works.sh —
#   1. ipfs add --hidden --cid-version 1   (--hidden is REQUIRED)
#   2. ipfs get the CID back and cmp against the source (byte-exact or it is
#      not a copy)
#   3. append to a manifest; leave the bytes in the blockstore
#
# Run this ON the pinning node, with the files already copied there.
#
# Usage:
#   ./pin-files.sh <manifest_out.csv> <file> [file ...]
# Env:
#   IPFS_BIN   (default ipfs)
#   IPFS_PATH  respected by ipfs as usual (ff-pin-1: /mnt/ff-pin-data/ipfs)

set -euo pipefail

MANIFEST="${1:?manifest output csv}"; shift
[[ $# -gt 0 ]] || { echo "no files given" >&2; exit 1; }
IPFS_BIN="${IPFS_BIN:-ipfs}"

[[ -f "$MANIFEST" ]] || echo "filename,cid,bytes,sha256,added_at,verified" > "$MANIFEST"

for f in "$@"; do
  name=$(basename "$f")
  if grep -q ",$name," "$MANIFEST" 2>/dev/null || grep -q "^$name," "$MANIFEST"; then
    echo "[$name] already in manifest, skipping"; continue
  fi
  [[ -f "$f" ]] || { echo "[$name] ERROR: not a file" >&2; exit 1; }

  bytes=$(stat -c%s "$f")
  sha=$(sha256sum "$f" | cut -d' ' -f1)
  echo "[$name] add ($bytes bytes)"
  cid=$("$IPFS_BIN" add -Q --hidden --cid-version 1 "$f")

  echo "[$name] verify"
  rt=$(mktemp)
  "$IPFS_BIN" cat "$cid" > "$rt"
  if ! cmp -s "$f" "$rt"; then
    echo "[$name] ERROR: round trip differs from source — not pinned" >&2
    rm -f "$rt"; exit 1
  fi
  rm -f "$rt"

  echo "$name,$cid,$bytes,$sha,$(date -u +%Y-%m-%dT%H:%M:%SZ),yes" >> "$MANIFEST"
  echo "[$name] ok  $cid"
  echo "   https://ipfs.feralfile.com/ipfs/$cid"
done

echo
echo "manifest: $MANIFEST"
echo "Record these in the archive manifest and point works.yaml at the URLs."
