#!/usr/bin/env python3
"""Batch-pin CIDs that are already present locally: one pin/add call per chunk
(default 100 CIDs) instead of one per CID, so kubo persists the pinset ~24
times for 2,341 CIDs rather than 2,341 times. No data is uploaded or fetched —
pin/add on present blocks is a local pinset operation.

  python3 tools/pin-referenced/batch_pin.py <cid_list.txt> [--chunk 100] \
      [--api http://127.0.0.1:5001/api/v0]

Resumable: already-pinned CIDs (recursive) are skipped up front; rerun after
any interruption. Verifies the full list against pin/ls at the end.
"""
import argparse, json, sys, time, urllib.parse, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument('list')
ap.add_argument('--chunk', type=int, default=100)
ap.add_argument('--api', default='http://127.0.0.1:5001/api/v0')
ap.add_argument('--timeout', type=int, default=600)
a = ap.parse_args()

def api(path, timeout):
    req = urllib.request.Request(f'{a.api}/{path}', method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()

cids = [l.strip() for l in open(a.list) if l.strip()]
try:
    pinned = set(json.loads(api('pin/ls?type=recursive', 300))['Keys'])
except Exception as e:
    sys.exit(f'no kubo API at {a.api}: {e}')
todo = [c for c in cids if c not in pinned]
print(f'{len(cids)} CIDs; {len(todo)} still to pin ({len(cids) - len(todo)} already pinned)', file=sys.stderr)

done = 0
for i in range(0, len(todo), a.chunk):
    chunk = todo[i:i + a.chunk]
    qs = '&'.join('arg=' + urllib.parse.quote(c) for c in chunk)
    t0 = time.time()
    body = api(f'pin/add?{qs}', a.timeout)
    # kubo streams errors after the 200 header — the success shape carries "Pins"
    okd = sum(len(json.loads(line).get('Pins', [])) for line in body.splitlines() if line.strip())
    if okd != len(chunk):
        sys.exit(f'chunk at offset {i}: pinned {okd}/{len(chunk)} — response tail: {body[-300:]}')
    done += okd
    print(f'[{done}/{len(todo)}] +{okd} in {time.time() - t0:.1f}s', file=sys.stderr)

pinned = set(json.loads(api('pin/ls?type=recursive', 300))['Keys'])
missing = [c for c in cids if c not in pinned]
print(f'verify: {len(cids) - len(missing)}/{len(cids)} pinned recursively; missing: {len(missing)}')
for c in missing[:20]:
    print('  NOT PINNED:', c)
sys.exit(1 if missing else 0)
