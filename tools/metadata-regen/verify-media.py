#!/usr/bin/env python3
"""Prove the media the regenerated metadata points at is fetchable WITHOUT
Feral File: for every plan.csv row, HEAD/GET the new animation_url and image
CIDs (query string stripped — gateways ignore it) through a public gateway and
through ipfs.feralfile.com. Run before pin.sh (media must already be public)
and again after the chain update as the acceptance check.

  python3 verify-media.py [plan.csv] [--public gw1,gw2,…] [--own https://ipfs.feralfile.com/ipfs/] [--workers 8]

Writes verify-media.csv: cid,path,<gateway>=<http code>…,ok. A CID passes when
our gateway serves it AND at least one public gateway does (2026-08-28: of 436
CIDs, 42 timed out (504) on ipfs.io alone but every one served from ipfs.io,
dweb.link or pinata — single-gateway 504s on large video are transient, a
'no providers' condition shows as 504 on all of them). Exit 1 if any CID fails.
"""
import argparse, csv, sys, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
ap = argparse.ArgumentParser(); ap.add_argument('plan', nargs='?', default='plan.csv')
ap.add_argument('--public', default='https://ipfs.io/ipfs/,https://dweb.link/ipfs/,https://gateway.pinata.cloud/ipfs/', help='public gateways; a CID passes if ANY of them serves it (large files time out on single gateways)')
ap.add_argument('--own', default='https://ipfs.feralfile.com/ipfs/', help='our gateway; must serve every CID')
ap.add_argument('--workers', type=int, default=8)
a = ap.parse_args(); PUB = a.public.split(','); gws = PUB + [a.own]
def cid_path(u):
    p = urllib.parse.urlparse(u); return p.netloc, p.path.rstrip('/')
targets = sorted({cid_path(u) for r in csv.DictReader(open(a.plan)) for u in (r['new_animation_url'], r['new_image']) if u.startswith('ipfs://')})
def probe(t):
    cid, path = t; row = {'cid': cid, 'path': path}; okk = True
    for g in gws:
        url = f'{g}{cid}{path}'
        try:
            req = urllib.request.Request(url, method='GET', headers={'User-Agent': 'metadata-regen/verify', 'Range': 'bytes=0-0'})
            code = urllib.request.urlopen(req, timeout=90).status
        except urllib.error.HTTPError as e: code = e.code
        except Exception as e: code = type(e).__name__
        row[g] = code
    row['ok'] = int(row[a.own] in (200, 206) and any(row[g] in (200, 206) for g in PUB)); return row
with ThreadPoolExecutor(a.workers) as ex: rows = list(ex.map(probe, targets))
# second pass, serial and slow, for the failures: public gateways rate-limit (429) under parallel load
import time
for i, r in enumerate(rows):
    if not r['ok']:
        time.sleep(3); rows[i] = probe((r['cid'], r['path']))
with open('verify-media.csv', 'w') as f:
    w = csv.DictWriter(f, ['cid', 'path', *gws, 'ok'], lineterminator='\n'); w.writeheader(); w.writerows(rows)
bad = [r for r in rows if not r['ok']]
print(f'{len(rows)} distinct media CIDs, {len(bad)} failing → verify-media.csv'); [print(' ', r) for r in bad[:20]]
sys.exit(1 if bad else 0)
