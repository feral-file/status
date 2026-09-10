#!/usr/bin/env python3
"""Phase-2 step 3 (crystalline): emit the artworks.metadata.ipfs_cid UPDATEs
after the setTokenBaseURI switch.

DB convention (measured 2026-09-02, v4_tokens_export): on V4 contracts
`artworks.metadata.ipfs_cid` holds a PATH `<dirCID>/<tokenId>` — the API
fetches it as-is. The align therefore swaps the dir root inside the path,
WHERE-pinned per token to the exact old value (phase-1 discipline), with
series_id as a second anchor (hls-fix style).

  python3 tools/db-align-sql/gen-v4-sql.py \
      --db-export ops/cdn-retirement-phase2/step2/crystalline_db_export.csv \
      --old-dir QmY67Gq1514Zj1yWtHxoHeoVj8FpFLM5ZNSNQejjirxKTo \
      --new-dir <newDirCID>  > crystalline-align.sql

Run only AFTER v4-base-uri.mjs broadcast has succeeded (the DB should
follow the chain, never lead it).
"""
import argparse, csv, re, sys

CID = re.compile(r'^(Qm[1-9A-HJ-NP-Za-km-z]{44}|baf[a-z0-9]{20,})$')
ap = argparse.ArgumentParser()
ap.add_argument('--db-export', required=True)
ap.add_argument('--old-dir', required=True)
ap.add_argument('--new-dir', required=True)
a = ap.parse_args()
if not CID.match(a.old_dir) or not CID.match(a.new_dir):
    sys.exit('old-dir/new-dir must be bare CIDs')

rows = list(csv.DictReader(open(a.db_export)))
skipped = 0
out = []
for r in rows:
    t, sid = r['token_id'], r['series_id']
    expect = f'{a.old_dir}/{t}'
    if r['ipfs_cid'] != expect:
        skipped += 1
        print(f"-- SKIP …{t[-10:]}: db ipfs_cid {r['ipfs_cid'][:50]}… != expected {a.old_dir[:20]}…/<id> — investigate", file=sys.stderr)
        continue
    if not t.isdigit() or not re.fullmatch(r'[0-9a-f-]{36}', sid):
        sys.exit(f'bad row: {r}')
    out.append((t, sid))
print(f'-- gen-v4-sql.py: {len(out)} artworks rows ({skipped} skipped); run in a transaction, check counts')
print('BEGIN;')
for t, sid in out:
    print(f"UPDATE artworks SET metadata = metadata || jsonb_build_object('ipfs_cid', '{a.new_dir}/{t}'), updated_at = now() "
          f"WHERE id = '{t}' AND series_id = '{sid}' AND metadata->>'ipfs_cid' = '{a.old_dir}/{t}';")
print(f'-- expect UPDATE 1 × {len(out)}; then COMMIT (or ROLLBACK)')
if skipped:
    sys.exit(1)
