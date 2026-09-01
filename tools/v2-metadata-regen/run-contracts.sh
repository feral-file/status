#!/usr/bin/env bash
# Drive the chain update across every contract, smallest first, in batches of
# $BATCH tokens (default 100), stopping on the first failure.
#
#   RPC_URL=… VAULT_URL=… VAULT_API_KEY=… [BATCH=100] ./run-contracts.sh [--dry-run]
#
# Per contract: updates/<c>.csv is split into runs/<c>/batches/NNN.csv, each with
# its own config (same workDir → one progress.json per contract). Per batch:
#   preflight (exit≠0 → stop) → run-all --yes (exit≠0 → stop) → check (any row
#   not updated → stop) → batch recorded in runs/<c>/batches/done.txt.
# After the last batch a full-contract check runs and the contract is recorded
# in runs/done.txt. Re-running resumes at the first unfinished batch; inside a
# batch, preflight marks rows already on chain DONE and run-all skips tokens in
# progress.json. Logs: runs/<c>/run.log
# Before starting (and after any long pause) do the quiet-window check on eth_tx
# for the trustee yourself — the script cannot see the server DB.
set -euo pipefail
cd "$(dirname "$0")"
: "${RPC_URL:?}" "${VAULT_URL:?}" "${VAULT_API_KEY:?}"
TOOL=../update-token-uri
DRY=${1:-}
BATCH=${BATCH:-100}
DONE=runs/done.txt; touch "$DONE"

mapfile -t ORDER < <(for f in updates/*.csv; do c=$(basename "$f" .csv); echo "$(( $(wc -l < "$f") - 1 )) $c"; done | sort -n | awk '{print $2}')

tool() { ( cd "$TOOL" && node update-token-uri.mjs "$@" ); }

for c in "${ORDER[@]}"; do
  cfg="$PWD/runs/$c/config.json"; log="runs/$c/run.log"; bdir="runs/$c/batches"
  [ -f "$cfg" ] || { echo "!! no config for $c — run make-configs.py"; exit 1; }
  if grep -qx "$c" "$DONE"; then echo "== $c already complete, skip"; continue; fi
  n=$(( $(wc -l < "updates/$c.csv") - 1 ))
  echo; echo "== $c ($n rows, batches of $BATCH) $(date -u +%FT%TZ)" | tee -a "$log"

  # split once (idempotent: skipped if batches already exist)
  mkdir -p "$bdir"; touch "$bdir/done.txt"
  if ! ls "$bdir"/[0-9][0-9][0-9].csv >/dev/null 2>&1; then
    hdr=$(head -1 "updates/$c.csv")
    tail -n +2 "updates/$c.csv" | split -l "$BATCH" -d -a 3 - "$bdir/part-"
    for p in "$bdir"/part-*; do i=${p##*-}; { echo "$hdr"; cat "$p"; } > "$bdir/$i.csv"; rm "$p"
      python3 - "$cfg" "$PWD/$bdir/$i.csv" "$PWD/$bdir/config-$i.json" <<'PY'
import json,sys; c=json.load(open(sys.argv[1])); c['updates']=sys.argv[2]; json.dump(c,open(sys.argv[3],'w'),indent=2)
PY
    done
  fi

  for b in "$bdir"/[0-9][0-9][0-9].csv; do
    i=$(basename "$b" .csv)
    grep -qx "$i" "$bdir/done.txt" && { echo "-- batch $i done, skip" | tee -a "$log"; continue; }
    export UPDATE_CONFIG="$PWD/$bdir/config-$i.json"
    echo "-- batch $i ($(( $(wc -l < "$b") - 1 )) rows) preflight $(date -u +%TZ)" | tee -a "$log"
    tool preflight 2>&1 | tee -a "$log" || { echo "!! preflight failed: $c batch $i — stopping"; exit 1; }
    [ "$DRY" = "--dry-run" ] && continue
    echo "-- batch $i run-all" | tee -a "$log"
    ( cd "$TOOL" && node run-all.mjs --yes ) 2>&1 | tee -a "$log" || { echo "!! run-all stopped: $c batch $i — inspect runs/$c/ (a vault-tx-*.json left behind = signed tx not relayed; check that nonce on Etherscan before resuming). Re-run this script to resume."; exit 1; }
    echo "-- batch $i check" | tee -a "$log"
    tool check 2>&1 | tee -a "$log" || { echo "!! check: not every row updated in $c batch $i — stopping"; exit 1; }
    echo "$i" >> "$bdir/done.txt"
  done
  [ "$DRY" = "--dry-run" ] && continue

  echo "-- full contract check" | tee -a "$log"
  export UPDATE_CONFIG="$cfg"
  tool check 2>&1 | tee -a "$log" || { echo "!! full check failed for $c — stopping"; exit 1; }
  echo "$c" >> "$DONE"; echo "== $c complete $(date -u +%FT%TZ)" | tee -a "$log"
done
echo; echo "all contracts complete: $(wc -l < "$DONE")/${#ORDER[@]}"
