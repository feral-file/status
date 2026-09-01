#!/usr/bin/env python3
"""Pin every CID the Feral File DB references on the serving node (prod-02).

  python3 pin_referenced.py <cid_list.txt> [--pin] [--workers 4] [--api http://127.0.0.1:5001/api/v0]

Background (feral-file#3435, 2026-08-27): prod-02 served 73k DB-referenced
CIDs but held only ~950 recursive pins — the rest were gateway-era cache,
never GC'd only because the container runs without --enable-gc. This makes
the referenced set explicit and pinned.

For each CID (skipping ones already pinned recursively):
  1. block/stat?offline=true  → present locally or not (no network fetch)
  2. if present and --pin:    pin/add (recursive). A directory whose children
     are missing would make pin/add fetch from the network; a per-call
     timeout turns that into "partial", listed for follow-up.
Output: <cid_list>.pinstatus.csv with cid,present,pinned,note, and a summary.
Resumable: rerun skips CIDs that are pinned by then.
"""
import argparse, csv, json, sys, time, concurrent.futures as cf, urllib.request, urllib.parse, urllib.error
ap = argparse.ArgumentParser()
ap.add_argument('list'); ap.add_argument('--pin', action='store_true'); ap.add_argument('--workers', type=int, default=4)
ap.add_argument('--api', default='http://127.0.0.1:5001/api/v0'); ap.add_argument('--pin-timeout', type=int, default=120)
a = ap.parse_args()

def api(path, timeout=60):
    req = urllib.request.Request(f'{a.api}/{path}', method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as r: return r.read().decode()

cids = [l.strip() for l in open(a.list) if l.strip()]
try: pinned = set(json.loads(api('pin/ls?type=recursive', 300))['Keys'])
except Exception as e: sys.exit(f'no kubo API at {a.api}: {e}')
print(f'{len(cids)} CIDs; {len(pinned)} recursive pins on the node now', file=sys.stderr)

def one(cid):
    if cid in pinned: return cid, 'yes', 'yes', 'already pinned'
    try: api(f'block/stat?arg={urllib.parse.quote(cid)}&offline=true', 30); present = 'yes'
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:80]
        return cid, 'no', 'no', 'missing locally' if 'not found' in body else body
    except Exception as e: return cid, '?', 'no', f'stat error {type(e).__name__}'
    if not a.pin: return cid, present, 'no', 'dry-run'
    try:
        out = api(f'pin/add?arg={urllib.parse.quote(cid)}&progress=false', a.pin_timeout)
        return cid, present, 'yes' if '"Pins"' in out else 'no', '' if '"Pins"' in out else out[:80]
    except Exception as e: return cid, present, 'no', f'pin timeout/err ({type(e).__name__}) — children probably missing'

rows = []; t0 = time.time()
with cf.ThreadPoolExecutor(a.workers) as ex:
    for i, r in enumerate(ex.map(one, cids), 1):
        rows.append(r)
        if i % 500 == 0 or i == len(cids):
            c = {}
            for _, p, pn, _ in rows: c[(p, pn)] = c.get((p, pn), 0) + 1
            print(f'[{i}/{len(cids)}] {int(time.time()-t0)}s {c}', file=sys.stderr)
out = a.list + '.pinstatus.csv'
with open(out, 'w', newline='') as f:
    w = csv.writer(f); w.writerow(['cid', 'present_locally', 'pinned', 'note']); w.writerows(rows)
present = sum(1 for r in rows if r[1] == 'yes'); pinned_n = sum(1 for r in rows if r[2] == 'yes'); missing = [r for r in rows if r[1] == 'no']
print(f'\npresent locally: {present}/{len(rows)}; pinned: {pinned_n}; missing locally: {len(missing)} (listed in {out})', file=sys.stderr)
if missing:
    with open(a.list + '.missing.txt', 'w') as f: f.write('\n'.join(r[0] for r in missing) + '\n')
    print(f'missing list: {a.list}.missing.txt — fetch these from ff-pin-1 / public gateways / origin before pinning', file=sys.stderr)
