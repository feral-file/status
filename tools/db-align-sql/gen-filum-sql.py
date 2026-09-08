#!/usr/bin/env python3
"""filum fix — DB align after the Truth setTokenBaseURI tx has landed.

Two changes, both WHERE-pinned to the exact current values (expect UPDATE 1 each):
  A. every Truth artwork (896): artworks.metadata.ipfs_cid -> '<newBase>/<tokenId>'
     — only rows whose current value is '<oldBase>/<tokenId>' (path form, as crystalline);
     rows in any other form are listed on stderr and NOT updated (investigate: the
     Truth DB may still carry an older doc generation, see truth-db-align.py).
  B. (OFF by default — decision 2026-09-08, Brandon: the display overlay is not part of the
     chain alignment; feralfile.com's display path stays as is) `--drop-overlay` adds:
     the 128 filum rows: remove metadata.alternativePreviewURI (the CDN overlay) —
     only where it equals the recorded value for that token (stored as the relative
     key `previews/71e2bed5…/1706081014/index.html?<params>`; the API prefixes the host)
     AND its query string equals the on-chain animation_url's (doc_updates.csv).
Run only AFTER v4-base-uri.mjs broadcast succeeded (DB follows the chain).

  python3 tools/db-align-sql/gen-filum-sql.py --db-export ops/cdn-retirement-phase2/filum/truth_db_export.csv \
      --cids ops/cdn-retirement-phase2/filum/cids.csv --doc-updates ops/cdn-retirement-phase2/filum/doc_updates.csv > filum-align.sql
"""
import argparse, csv, re, sys
ap = argparse.ArgumentParser()
ap.add_argument('--db-export', required=True); ap.add_argument('--cids', required=True); ap.add_argument('--doc-updates', required=True)
ap.add_argument('--drop-overlay', action='store_true', help='also emit the 128 alternativePreviewURI removals (off by default)')
a = ap.parse_args()
cids = {r['what'].split()[0]: r for r in csv.DictReader(open(a.cids))}
old_base, new_base = cids['base_dir']['old_cid'], cids['base_dir']['new_cid']
filum = {r['token_id']: r['old_animation_url'].split('?', 1)[1] for r in csv.DictReader(open(a.doc_updates))}
rows = list(csv.DictReader(open(a.db_export)))
# stored form measured 2026-09-08: a RELATIVE key (the API prefixes the CDN host); accept the full URL too
CDN = ('previews/71e2bed5-e224-4ead-8fea-88a8cc067dbe/1706081014/index.html?',
       'https://cdn.feralfileassets.com/previews/71e2bed5-e224-4ead-8fea-88a8cc067dbe/1706081014/index.html?')
def q(s): return s.replace("'", "''")
A, B, skipped, overlay_other = [], [], [], []
for r in rows:
    t, sid = r['token_id'], r['series_id']
    if not t.isdigit() or not re.fullmatch(r'[0-9a-f-]{36}', sid): sys.exit(f'bad row {r}')
    if r['ipfs_cid'] == f'{old_base}/{t}': A.append((t, sid))
    else: skipped.append((t, r['series_title'], r['ipfs_cid']))
    ov = r['alternative_preview_uri'] or ''
    if t in filum:
        if ov.startswith(CDN) and ov.split('?', 1)[1] == filum[t]: B.append((t, sid, ov))
        else: overlay_other.append((t, ov))
    elif ov: overlay_other.append((t, ov))
for t, s, c in skipped: print(f'-- SKIP ipfs_cid not in path form: {t} ({s}): {c[:60]}', file=sys.stderr)
for t, ov in overlay_other: print(f'-- NOTE overlay unexpected/missing: {t}: {ov[:60]}', file=sys.stderr)
if not a.drop_overlay:
    print(f'-- overlay: {len(B)} filum rows carry alternativePreviewURI; KEPT (no --drop-overlay)', file=sys.stderr)
    B = []
print(f'-- gen-filum-sql.py: A={len(A)} ipfs_cid path swaps ({len(skipped)} skipped), B={len(B)} overlay drops{"" if a.drop_overlay else " (overlay kept by decision 2026-09-08)"}; run in a transaction, check counts')
print('BEGIN;')
for t, sid in A:
    print(f"UPDATE artworks SET metadata = metadata || jsonb_build_object('ipfs_cid', '{new_base}/{t}'), updated_at = now() "
          f"WHERE id = '{t}' AND series_id = '{sid}' AND metadata->>'ipfs_cid' = '{old_base}/{t}';")
for t, sid, ov in B:
    print(f"UPDATE artworks SET metadata = metadata - 'alternativePreviewURI', updated_at = now() "
          f"WHERE id = '{t}' AND series_id = '{sid}' AND metadata->>'alternativePreviewURI' = '{q(ov)}';")
print(f'-- expect UPDATE 1 × {len(A) + len(B)}; then COMMIT (or ROLLBACK)')
if skipped or (a.drop_overlay and overlay_other): sys.exit(1)
