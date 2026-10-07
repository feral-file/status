#!/usr/bin/env python3
"""Self-contained DB align for `artworks.metadata.ipfs_cid` from the per-token
updates CSVs alone — no DB export needed, so it runs from a GUI client
(DBeaver) as well as psql.

Same discipline as gen-v3-sql.py (the DB follows the chain; every UPDATE
WHERE-pinned to the exact old value; nothing is committed by the script),
but the old→new mapping rides inside the SQL as a VALUES list, and each file
reports counts you can read before deciding:

  <out-dir>/01-precheck.sql   read-only: per-series and total — tokens in the
                              map, found in artworks, holding the old CID,
                              already holding the new CID, holding something
                              else (must be 0)
  <out-dir>/02-align.sql      BEGIN; UPDATE … FROM (VALUES …) WHERE id = token
                              AND metadata->>'ipfs_cid' = old; then the same
                              counts again (all rows must now hold the new
                              CID). Ends WITHOUT COMMIT — run it with
                              auto-commit off, read the counts, then COMMIT
                              or ROLLBACK yourself.

  python3 tools/db-align-sql/gen-map-sql.py --updates ops/…/step3/updates_*.csv --out-dir ops/…/step2

Input: updates CSVs with token_id,old_metadata_cid,new_metadata_cid columns
(pin-docs.py output). artworks.id = the decimal token id on both chains.
"""
import argparse, csv, os, re, sys

CID = re.compile(r'^(Qm[1-9A-HJ-NP-Za-km-z]{44}|baf[a-z0-9]{20,})$')
ap = argparse.ArgumentParser()
ap.add_argument('--updates', nargs='+', required=True)
ap.add_argument('--out-dir', required=True)
a = ap.parse_args()

rows = {}
for path in a.updates:
    for r in csv.DictReader(open(path)):
        t, old, new = r['token_id'], r['old_metadata_cid'], r['new_metadata_cid']
        if not t.isdigit() or not CID.match(old) or not CID.match(new) or old == new:
            sys.exit(f'{path}: bad row {r}')
        if t in rows:
            sys.exit(f'duplicate token_id across updates files: {t}')
        rows[t] = (old, new)
n = len(rows)
values = ',\n'.join(f"('{t}','{old}','{new}')" for t, (old, new) in sorted(rows.items()))

COUNTS = """SELECT CASE WHEN grouping(se.title) = 1 THEN 'TOTAL' ELSE coalesce(se.title, '(token not in artworks)') END AS series,
       count(*)                                                   AS in_map,
       count(a.id)                                                AS found,
       count(*) FILTER (WHERE a.metadata->>'ipfs_cid' = m.old_cid) AS holds_old,
       count(*) FILTER (WHERE a.metadata->>'ipfs_cid' = m.new_cid) AS holds_new,
       count(*) FILTER (WHERE a.id IS NOT NULL
                          AND a.metadata->>'ipfs_cid' IS DISTINCT FROM m.old_cid
                          AND a.metadata->>'ipfs_cid' IS DISTINCT FROM m.new_cid) AS holds_other
FROM map m
LEFT JOIN artworks a ON a.id = m.token_id
LEFT JOIN series se ON se.id = a.series_id
GROUP BY ROLLUP (se.title)
ORDER BY grouping(se.title), se.title NULLS LAST"""

os.makedirs(a.out_dir, exist_ok=True)
with open(os.path.join(a.out_dir, '01-precheck.sql'), 'w') as f:
    f.write(f"""-- gen-map-sql.py: READ-ONLY pre-check for {n} tokens (hidden-exhibition CDN retirement).
-- Expected before the align: every series row found = in_map = holds_old, holds_new = 0, holds_other = 0;
-- the last row (TOTAL) sums them.
WITH map(token_id, old_cid, new_cid) AS (VALUES
{values}
)
{COUNTS};
""")
with open(os.path.join(a.out_dir, '02-align.sql'), 'w') as f:
    f.write(f"""-- gen-map-sql.py: align artworks.metadata.ipfs_cid for {n} tokens — the DB follows the chain.
-- Each row is WHERE-pinned to the exact old CID: a drifted row yields no update, never a wrong write.
-- Run with AUTO-COMMIT OFF. The script ends without COMMIT: read the counts the last query prints
-- (every series: holds_new = in_map, holds_old = 0, holds_other = 0; UPDATE count = {n}), then run
-- COMMIT; — or ROLLBACK; if anything is off.
BEGIN;
WITH map(token_id, old_cid, new_cid) AS (VALUES
{values}
)
UPDATE artworks a
SET metadata = a.metadata || jsonb_build_object('ipfs_cid', m.new_cid), updated_at = now()
FROM map m
WHERE a.id = m.token_id AND a.metadata->>'ipfs_cid' = m.old_cid;
-- expect: UPDATE {n}

WITH map(token_id, old_cid, new_cid) AS (VALUES
{values}
)
{COUNTS};
-- now: COMMIT;  (or ROLLBACK;)
""")
print(f'{n} tokens → {a.out_dir}/01-precheck.sql, 02-align.sql', file=sys.stderr)
