#!/usr/bin/env python3
"""Probe every CID the Feral File Archive manifest names, through public gateways.

  python3 probe.py [--gateways ipfs.io,dweb.link,ipfs.feralfile.com] [--timeout 90] [--out data/archive_probe_<date>.csv]

Reads data/archive-manifest.json (all collections) and data/pin_manifest_*.csv
(the 215 series, in case the manifest lags), dedupes CIDs, and for each CID
and gateway issues one HEAD (redirects followed — dweb.link 301s to a
subdomain; directory CIDs answer on the listing). A CID "resolves" on a
gateway when it answers 2xx within the timeout. Output: one row per CID with
a column per gateway, plus a summary to stderr.

This is the check behind manifest condition #2 (feral-file#3435, 2026-08-26):
"every CID in the archive manifest resolves over public gateways". It only
tells you whether SOME provider answered the gateway; it does not say who.
Directory CIDs are probed at the root only — a root that answers with all
children missing (the prod-02 failure of 2026-08) would still pass here; use
`--deep` to also HEAD one child of every directory (slower).
"""
import argparse, csv, json, os, sys, time, glob, collections, urllib.request, urllib.error
from datetime import datetime, timezone
root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
ap = argparse.ArgumentParser()
ap.add_argument('--gateways', default='ipfs.io,dweb.link,ipfs.feralfile.com')
ap.add_argument('--timeout', type=int, default=90)
ap.add_argument('--gap', type=float, default=0.5, help='seconds between requests to the same gateway')
ap.add_argument('--deep', action='store_true', help='also probe one child of each directory CID')
ap.add_argument('--out')
a = ap.parse_args()
gws = [g.strip() for g in a.gateways.split(',') if g.strip()]

cids = {}  # cid -> label
m = json.load(open(os.path.join(root, 'data/archive-manifest.json')))
for c in m['collections']:
    for it in c.get('items') or c.get('entries') or c.get('series') or []:
        cids[it['cid']] = f"{c['id']}: {it.get('label') or it.get('title') or it.get('series_id')}"
pm = sorted(glob.glob(os.path.join(root, 'data/pin_manifest_*.csv')))
if pm:
    for r in csv.DictReader(open(pm[-1])):
        cids.setdefault(r['cid'], f"pin_manifest: {r['series_id']}")
print(f'{len(cids)} distinct CIDs from archive-manifest.json' + (f' + {os.path.basename(pm[-1])}' if pm else ''), file=sys.stderr)

last = collections.defaultdict(float)
def head(url):
    wait = a.gap - (time.time() - last[url.split('/')[2]])
    if wait > 0: time.sleep(wait)
    last[url.split('/')[2]] = time.time()
    req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'ff-archive-probe/1'})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=a.timeout) as r:
            return f'ok {r.status} {r.headers.get("Content-Type","")[:24]} {time.time()-t0:.1f}s'
    except urllib.error.HTTPError as e:
        return f'fail: HTTP {e.code} {time.time()-t0:.1f}s'
    except Exception as e:
        return f'fail: {type(e).__name__} {str(e)[:40]} {time.time()-t0:.1f}s'

def first_child(cid, gw):
    # ask the gateway for a dag-json listing of the directory root
    req = urllib.request.Request(f'https://{gw}/ipfs/{cid}/?format=dag-json', headers={'Accept': 'application/vnd.ipld.dag-json'})
    try:
        with urllib.request.urlopen(req, timeout=a.timeout) as r:
            d = json.load(r)
        links = d.get('Links') or []
        return links[0].get('Name') if links else None
    except Exception:
        return None

stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M%SZ')
out = a.out or os.path.join(root, f'data/archive_probe_{stamp}.csv')
cols = ['cid', 'label'] + [f'{g.replace(".", "_").replace("-", "_")}_ok' for g in gws] + (['child_probe'] if a.deep else [])
rows = []
for i, (cid, label) in enumerate(cids.items(), 1):
    row = {'cid': cid, 'label': label}
    for g, col in zip(gws, cols[2:2+len(gws)]):
        row[col] = head(f'https://{g}/ipfs/{cid}')
    if a.deep:
        child = first_child(cid, gws[0])
        row['child_probe'] = head(f'https://{gws[0]}/ipfs/{cid}/{child}') if child else 'no listing / not a directory'
    rows.append(row)
    print(f'[{i}/{len(cids)}] {cid[:16]}… ' + ' | '.join(f'{g}={row[c][:12]}' for g, c in zip(gws, cols[2:2+len(gws)])), file=sys.stderr)
with open(out, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
print(f'\nwritten {out}', file=sys.stderr)
for g, col in zip(gws, cols[2:2+len(gws)]):
    ok = sum(1 for r in rows if r[col].startswith('ok'))
    print(f'  {g}: {ok}/{len(rows)} resolve', file=sys.stderr)
    for r in rows:
        if not r[col].startswith('ok'): print(f'     FAIL {r["cid"]} ({r["label"][:40]}) {r[col]}', file=sys.stderr)
