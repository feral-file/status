#!/usr/bin/env python3
"""Phase-2 step 2 (Truth): align artworks.metadata.ipfs_cid to the on-chain docs.

Truth (`0xBb12686c…`, V4) needs no metadata regen and no tx — the on-chain
directory docs are already all-`ipfs://` (v4_audit_truth.csv,
chain_needs_fix 0). The DB still points at the superseded doc generation
(CDN media), which is what the API serves. This tool finishes the
bookkeeping that the original rebuild never did, with the safety diff the
plan requires (Revision 2026-09-02):

Per token, BEFORE any SQL is emitted:
  1. fetch the OLD doc (the DB's ipfs_cid) and the CHAIN doc (the audit's
     doc_cid) via the gateway;
  2. diff them as JSON — every key must be equal EXCEPT the media keys
     (`image`, `animation_url`, and `thumbnailURI`-style variants); a token
     differing anywhere else drops out of the batch (manual review);
  3. collect every ipfs:// media CID the chain doc references and probe it
     on ipfs.feralfile.com + ipfs.io — the DB flip makes the API serve
     these, so they must resolve first.

DB export format (operator, via the back-office host):
  CSV with header: artwork_id,token_id,ipfs_cid
  (artworks.id, the on-chain decimal token id, metadata->>'ipfs_cid')

Usage:
  python3 tools/phase2-step2/truth-db-align.py \
      --db-export ops/cdn-retirement-phase2/step2/truth_db_export.csv \
      --audit ops/cdn-retirement-phase2/step0/v4_audit_truth.csv \
      --out-dir ops/cdn-retirement-phase2/step2

Outputs: diff_report.csv (verdict per token), media_probe.csv,
truth-align.sql (only clean-verdict tokens; WHERE-pinned to the old CID,
expect UPDATE 1 each). Exit 1 if any token fails the diff or any media CID
fails on ipfs.feralfile.com.
"""
import argparse, csv, json, os, sys, time, urllib.request

MEDIA_KEYS = {'image', 'animation_url', 'thumbnailURI', 'thumbnail_uri', 'artifactUri', 'displayUri'}

ap = argparse.ArgumentParser()
ap.add_argument('--db-export', required=True)
ap.add_argument('--audit', required=True)
ap.add_argument('--out-dir', required=True)
ap.add_argument('--gateway', default='https://ipfs.feralfile.com')
ap.add_argument('--timeout', type=float, default=60)
a = ap.parse_args()
os.makedirs(a.out_dir, exist_ok=True)

def fetch_json(cid):
    for attempt in range(3):
        try:
            return json.load(urllib.request.urlopen(f'{a.gateway}/ipfs/{cid}', timeout=a.timeout))
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))

def probe(url):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, method='GET'), timeout=a.timeout)
        return r.status in (200, 206)
    except Exception:
        return False

audit = {r['token_id']: r for r in csv.DictReader(open(a.audit))}
export = list(csv.DictReader(open(a.db_export)))
need = {'artwork_id', 'token_id', 'ipfs_cid'}
if not need.issubset(export[0].keys()):
    sys.exit(f'db export must have columns {need}, got {list(export[0].keys())}')

doc_cache = {}
report, sql_rows, media_cids = [], [], {}
for e in export:
    t = e['token_id']
    au = audit.get(t)
    if not au:
        report.append([t, e['artwork_id'], e['ipfs_cid'], '', 'NOT_IN_AUDIT', ''])
        continue
    old_cid, new_cid = e['ipfs_cid'], au['doc_cid']
    if old_cid == new_cid:
        report.append([t, e['artwork_id'], old_cid, new_cid, 'already_aligned', ''])
        continue
    try:
        old = doc_cache.setdefault(old_cid, fetch_json(old_cid))
        new = doc_cache.setdefault(new_cid, fetch_json(new_cid))
    except Exception as ex:
        report.append([t, e['artwork_id'], old_cid, new_cid, 'FETCH_ERROR', str(ex)[:120]])
        continue
    bad = [k for k in set(old) | set(new)
           if old.get(k) != new.get(k) and k not in MEDIA_KEYS]
    verdict = 'ok' if not bad else 'DIFF_BEYOND_MEDIA'
    report.append([t, e['artwork_id'], old_cid, new_cid, verdict,
                   ';'.join(sorted(bad))[:200]])
    if verdict == 'ok':
        sql_rows.append((e['artwork_id'], t, old_cid, new_cid))
        for k in MEDIA_KEYS:
            v = new.get(k) or ''
            if v.startswith('ipfs://'):
                media_cids.setdefault(v[7:].split('?')[0].split('/')[0], []).append(t)

with open(os.path.join(a.out_dir, 'diff_report.csv'), 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['token_id', 'artwork_id', 'db_cid_old', 'chain_doc_cid', 'verdict', 'detail'])
    w.writerows(report)

print(f'probing {len(media_cids)} distinct media CIDs the chain docs reference…', flush=True)
ff_fail = []
with open(os.path.join(a.out_dir, 'media_probe.csv'), 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['cid', 'n_tokens', 'ipfs_feralfile_com', 'ipfs_io'])
    for cid, toks in sorted(media_cids.items()):
        ff = probe(f'https://ipfs.feralfile.com/ipfs/{cid}')
        pub = probe(f'https://ipfs.io/ipfs/{cid}')
        w.writerow([cid, len(toks), 'ok' if ff else 'FAIL', 'ok' if pub else 'FAIL'])
        if not ff:
            ff_fail.append(cid)
        time.sleep(1)

with open(os.path.join(a.out_dir, 'truth-align.sql'), 'w') as f:
    f.write(f'-- truth-db-align.py: {len(sql_rows)} artworks rows; run in a transaction, check counts\nBEGIN;\n')
    for aid, t, old, new in sql_rows:
        f.write(f"UPDATE artworks SET metadata = metadata || jsonb_build_object('ipfs_cid', '{new}'), updated_at = now() "
                f"WHERE id = '{aid}' AND metadata->>'ipfs_cid' = '{old}';\n")
    f.write(f'-- expect UPDATE 1 × {len(sql_rows)}; then COMMIT (or ROLLBACK)\n')

counts = {}
for r in report:
    counts[r[4]] = counts.get(r[4], 0) + 1
print('verdicts:', counts)
print(f'sql rows: {len(sql_rows)} -> truth-align.sql; media CIDs failing on ipfs.feralfile.com: {len(ff_fail)}')
if ff_fail:
    print('  pin these on prod-02 BEFORE the SQL (tools/pin-referenced or ipfs pin add):')
    for c in ff_fail:
        print(f'   {c}')
bad = [r for r in report if r[4] in ('DIFF_BEYOND_MEDIA', 'FETCH_ERROR', 'NOT_IN_AUDIT')]
if bad or ff_fail:
    sys.exit(1)
