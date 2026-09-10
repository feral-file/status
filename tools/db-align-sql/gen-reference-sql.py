#!/usr/bin/env python3
"""Phase-2 step 2: emit ipfs_reference rows for the phase-2 artworks.

For every artwork in the export(s), map its `preview_uri` / `thumbnail_uri`
(CDN-relative paths like `previews/<uuid>/<ts>/index.html?edition_number=…`)
onto the step-1b pin units and emit ipfs_reference upserts pointing at
`ipfs://<unitCID>/<subpath>?<params>` — query params preserved byte-for-byte
(phase-1 rule; crystalline's `?hourIdx=N` and software `?edition_number=…`
both ride along).

Safety split (same spirit as phase 1's "prefer the ensure tasks"):
  - URI has NO reference row yet            → INSERT … ON CONFLICT DO NOTHING
  - URI already has a row, SAME target      → skipped (counted)
  - URI already has a row, DIFFERENT target → NOT updated; written to
    conflicts.csv for review (never clobber an existing reference blindly)
  - URI maps to no pin unit                 → unmapped.csv (investigate)

  python3 tools/db-align-sql/gen-reference-sql.py \
      --dir-cids ops/cdn-retirement-phase2/step1/dir_cids.csv \
      --out-dir ops/cdn-retirement-phase2/step2 \
      ops/cdn-retirement-phase2/step2/v3_tokens_export.csv \
      ops/cdn-retirement-phase2/step2/crystalline_db_export.csv \
      > reference-rows.sql
"""
import argparse, csv, os, sys

ap = argparse.ArgumentParser()
ap.add_argument('exports', nargs='+')
ap.add_argument('--dir-cids', required=True)
ap.add_argument('--out-dir', required=True)
a = ap.parse_args()
CDN_PREFIX = 'https://cdn.feralfileassets.com/'

dir_map, file_map = {}, {}
for r in csv.DictReader(open(a.dir_cids)):
    if not r['cid']:
        continue
    key = r['dir_or_file']
    rel = key[len(CDN_PREFIX):] if key.startswith(CDN_PREFIX) else key
    if key.endswith('/'):
        dir_map[rel] = f"ipfs://{r['cid']}/"
    else:
        file_map[rel] = f"ipfs://{r['cid']}"

def map_uri(u):
    base = u.split('?', 1)[0]
    for unit, pref in dir_map.items():
        if u.startswith(unit):
            return pref + u[len(unit):]
    if base in file_map:
        return file_map[base] + u[len(base):]
    return None

todo = {}            # uri -> ipfs target (deduped across tokens sharing a uri)
same = 0
conflicts, unmapped = [], []
for path in a.exports:
    for r in csv.DictReader(open(path)):
        for uri_col, ref_col in (('preview_uri', 'preview_ipfs_uri'),
                                 ('thumbnail_uri', 'thumbnail_ipfs_uri')):
            uri = (r.get(uri_col) or '').strip()
            if not uri or uri.startswith('ipfs://'):
                continue
            target = map_uri(uri)
            if target is None:
                unmapped.append([r['contract'], r['token_id'], uri_col, uri])
                continue
            existing = (r.get(ref_col) or '').strip()
            if existing:
                if existing == target:
                    same += 1
                else:
                    conflicts.append([r['contract'], r['token_id'], uri_col, uri, existing, target])
                continue
            prev = todo.get(uri)
            if prev and prev != target:
                sys.exit(f'internal: uri {uri} maps to two targets {prev} / {target}')
            todo[uri] = target

os.makedirs(a.out_dir, exist_ok=True)
def dump(name, header, rows):
    with open(os.path.join(a.out_dir, name), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
dump('reference_conflicts.csv', ['contract', 'token_id', 'col', 'uri', 'existing_ipfs_uri', 'computed_ipfs_uri'],
     sorted(set(map(tuple, conflicts))))
dump('reference_unmapped.csv', ['contract', 'token_id', 'col', 'uri'], sorted(set(map(tuple, unmapped))))

q = lambda s: s.replace("'", "''")
print(f'-- gen-reference-sql.py: {len(todo)} new ipfs_reference rows '
      f'({same} already-correct skipped, {len(set(map(tuple, conflicts)))} conflicts NOT touched, '
      f'{len(set(map(tuple, unmapped)))} unmapped)')
print('BEGIN;')
for uri in sorted(todo):
    print(f"INSERT INTO ipfs_reference (uri, ipfs_uri) VALUES ('{q(uri)}', '{q(todo[uri])}') "
          f"ON CONFLICT (uri) DO NOTHING;")
print(f'-- expect INSERT 0 1 × {len(todo)}; then COMMIT (or ROLLBACK)')
if conflicts or unmapped:
    print(f'REVIEW NEEDED: {len(set(map(tuple, conflicts)))} conflicts, '
          f'{len(set(map(tuple, unmapped)))} unmapped — see csvs in {a.out_dir}', file=sys.stderr)
    sys.exit(1)
