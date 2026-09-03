#!/usr/bin/env python3
"""Phase-2 V3 DB align: emit the artworks.metadata.ipfs_cid UPDATEs after the
per-token chain rollout (2,341 updateArtworkEditionIPFSCid txs, 2026-09-03).

The chain now points every fixed V3 token at its NEW metadata doc CID; the DB
still holds the old one. Same discipline as gen-v4-sql.py: WHERE pinned per
token to the exact old value, series_id as a second anchor, run in a
transaction, the DB follows the chain and never leads it.

Unlike V4 there is no single dir swap — the old→new mapping is per token,
from the six step3/updates_0x*.csv files that drove run-contracts.sh.

The V3 storage form was TBC at handoff time (bare CID vs some path/suffix
form): this tool measures it from the export instead of assuming. A DB value
of exactly `<old_cid>` or `<old_cid><suffix>` (e.g. `/metadata.json`) maps to
`<new_cid>` with the same suffix preserved; anything else is SKIPped to
stderr for investigation and the run exits 1.

  python3 tools/db-align-sql/gen-v3-sql.py \
      --db-export ops/cdn-retirement-phase2/step2/v3_tokens_export.csv \
      --updates ops/cdn-retirement-phase2/step3/updates_0x*.csv \
      > v3-align.sql
"""
import argparse, csv, re, sys

CID = re.compile(r'^(Qm[1-9A-HJ-NP-Za-km-z]{44}|baf[a-z0-9]{20,})$')
ap = argparse.ArgumentParser()
ap.add_argument('--db-export', required=True)
ap.add_argument('--updates', nargs='+', required=True,
                help='step3/updates_0x*.csv files (edition,token_id,old_metadata_cid,new_metadata_cid)')
a = ap.parse_args()

mapping = {}  # token_id -> (old_cid, new_cid)
for path in a.updates:
    for r in csv.DictReader(open(path)):
        t, old, new = r['token_id'], r['old_metadata_cid'], r['new_metadata_cid']
        if not CID.match(old) or not CID.match(new):
            sys.exit(f'{path}: bad CID row {r}')
        if t in mapping:
            sys.exit(f'duplicate token_id across updates files: {t}')
        mapping[t] = (old, new)

db = {}  # token_id -> export row
for r in csv.DictReader(open(a.db_export)):
    db[r['token_id']] = r

missing, skipped, already, out = [], 0, 0, []
forms = {}
for t, (old, new) in sorted(mapping.items()):
    r = db.get(t)
    if r is None:
        missing.append(t)
        continue
    cur, sid = r['ipfs_cid'], r['series_id']
    if not t.isdigit() or not re.fullmatch(r'[0-9a-f-]{36}', sid):
        sys.exit(f'bad export row: {r}')
    if cur == new or (cur.startswith(new) and cur[len(new):].startswith('/')):
        already += 1
        continue
    if cur == old:
        suffix = ''
    elif cur.startswith(old) and cur[len(old):].startswith('/'):
        suffix = cur[len(old):]
    else:
        skipped += 1
        print(f'-- SKIP …{t[-10:]}: db ipfs_cid {cur[:60]!r} matches neither old {old[:16]}… nor new — investigate', file=sys.stderr)
        continue
    forms[suffix or '<bare>'] = forms.get(suffix or '<bare>', 0) + 1
    out.append((t, sid, cur, new + suffix))

if missing:
    print(f'-- {len(missing)} mapped tokens absent from the export (first: …{missing[0][-10:]}) — export stale?', file=sys.stderr)
print(f'-- gen-v3-sql.py: {len(out)} artworks rows ({already} already aligned, {skipped} skipped, {len(missing)} missing); '
      f'value forms: {forms}; run in a transaction, check counts')
print('BEGIN;')
for t, sid, cur, new_val in out:
    print(f"UPDATE artworks SET metadata = metadata || jsonb_build_object('ipfs_cid', '{new_val}'), updated_at = now() "
          f"WHERE id = '{t}' AND series_id = '{sid}' AND metadata->>'ipfs_cid' = '{cur}';")
print(f'-- expect UPDATE 1 × {len(out)}; then COMMIT (or ROLLBACK)')
if skipped or missing:
    sys.exit(1)
