#!/usr/bin/env python3
"""Pass 1: walk the whole indexer-v2 token index (GraphQL, 255/page) and record, per token,
contract / publisher / token_number / burned / viewable and the indexer's derived media URLs.
Purpose: the census universe is FF-API exhibitions only, so contracts deployed from our
deployer address but never published as an exhibition (the OpenSea 'special-project' class)
are invisible to it. The indexer registry indexes by deployer address, so this walk is the
authoritative population. Resumable via --state (offset)."""
import csv, json, os, sys, time, urllib.request
GQL = 'https://indexer-v2.feralfile.com/graphql'
out = sys.argv[1]; state = out + '.state'
offset = int(open(state).read()) if os.path.exists(state) else 0
Q = '''query($o:Uint64,$l:Uint8){ tokens(limit:$l, offset:$o, include_unviewable:true, include_moderated:true, chains:"eip155:1") { offset items {
  id chain standard contract_address token_number burned viewable release_id
  display { publisher { name } mime_type } } } }'''
# NB: no metadata{} here on purpose — some tokens carry multi-MB data: URIs in image_url and a
# 255-row page then arrives truncated (seen at offset 36465, 2026-09-08). Media is measured per
# contract in pass 2 (audit-contracts.py, origin_json, 100/page).
def q1(o, l):
    body = json.dumps({'query': Q, 'variables': {'o': o, 'l': l}}).encode()
    r = urllib.request.urlopen(urllib.request.Request(GQL, body, {'content-type': 'application/json'}), timeout=300)
    d = json.load(r)
    if 'errors' in d: raise RuntimeError(d['errors'])
    return d['data']['tokens']['items']
def q(o):
    """Adaptive page size: some tokens carry multi-MB fields (data: URIs in image_url), and a
    255-row page then exceeds what the server streams intact (truncated JSON / IncompleteRead,
    seen at offset 36465 on 2026-09-08). Fall back to smaller pages and stitch 255 rows."""
    for l in (255, 50, 10, 1):
        try:
            if l == 255: return q1(o, 255)
            items = []
            while len(items) < 255:
                chunk = q1(o + len(items), l)
                items += chunk
                if len(chunk) < l: break
            return items
        except Exception as e:
            print(f'offset {o}: page size {l} failed ({type(e).__name__}); shrinking', file=sys.stderr, flush=True)
            time.sleep(2)
    raise RuntimeError(f'offset {o}: unreadable even 1 row at a time')
new = not os.path.exists(out) or offset == 0
f = open(out, 'a' if not new else 'w', newline='')
w = csv.writer(f, lineterminator='\n')
if new: w.writerow(['id', 'chain', 'standard', 'contract_address', 'token_number', 'burned', 'viewable', 'release_id', 'publisher', 'mime_type'])
n = 0
while True:
    items = q(offset)
    if not items: break
    for t in items:
        d = t.get('display') or {}
        w.writerow([t['id'], t['chain'], t['standard'], (t['contract_address'] or '').lower(), t['token_number'], t['burned'], t['viewable'], t['release_id'],
                    ((d.get('publisher') or {}).get('name') or ''), d.get('mime_type') or ''])
    n += len(items); offset += len(items); f.flush(); open(state, 'w').write(str(offset))
    if (offset // 255) % 20 == 0: print(f'offset {offset}', file=sys.stderr, flush=True)
    if len(items) < 255: break
print(f'done: {n} tokens this run, final offset {offset}', file=sys.stderr)
