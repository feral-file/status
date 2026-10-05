#!/usr/bin/env python3
"""Independent verification of regenerated metadata docs (V3 and Tezos plans)
that does not need the CDN to be up.

`verify-regen.py` proves media 1:1 by fetching the OLD value from the CDN; on
2026-10-05 `cdn.feralfileassets.com` no longer resolved, so that proof cannot
run. Here the media proof is the registry's own (`tools/ipfs-mirror` byte-
compares every unit origin-copy vs gateway before recording it); this tool
proves the rest from the artifacts alone, sharing no code with the regen tools:

A. Doc integrity, per token — reverse-substitution: in the NEW doc bytes put
   each registry unit's `ipfs://<cid>` back to its CDN URL; the result must
   equal the ORIGINAL on-chain doc byte-for-byte, the new doc must differ from
   it, and must not contain the CDN host.
B. Servability (skipped with --no-gateway), deduped: every `ipfs://` media URI
   of the new docs answers 200/206 on the gateway (directory URIs must serve
   their index.html, which is also scanned for CDN or root-absolute
   references that would break off the CDN).

  python3 tools/metadata-regen/verify-docs.py --dir-cids dir_cids.csv \
      --plan v3-docs/plan.csv --src v3-src [--plan tezos-docs/plan.csv --src tezos-src] \
      --report verify_docs.csv [--no-gateway]

--plan/--src are given in pairs (plan.csv of v3-doc-regen.py / tezos-doc-regen.py
and the cache dir holding <old cid>.json). Exit 1 on any failure.
"""
import argparse, csv, json, os, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

CDN_HOST = b'feralfileassets.com'
ap = argparse.ArgumentParser()
ap.add_argument('--dir-cids', required=True)
ap.add_argument('--plan', action='append', required=True)
ap.add_argument('--src', action='append', required=True)
ap.add_argument('--report', required=True)
ap.add_argument('--gateway', default='https://ipfs.feralfile.com/ipfs/')
ap.add_argument('--no-gateway', action='store_true')
ap.add_argument('--workers', type=int, default=8)
a = ap.parse_args()
if len(a.plan) != len(a.src):
    sys.exit('give one --src per --plan')

back = []   # (new bytes, old bytes), longest first
for r in csv.DictReader(open(a.dir_cids)):
    if r['cid']:
        unit = r['dir_or_file']
        new = f"ipfs://{r['cid']}/" if unit.endswith('/') else f"ipfs://{r['cid']}"
        back.append((new.encode(), unit.encode()))
back.sort(key=lambda x: -len(x[0]))

def strings(o):
    if isinstance(o, str): yield o
    elif isinstance(o, dict):
        for v in o.values(): yield from strings(v)
    elif isinstance(o, list):
        for v in o: yield from strings(v)

report, media, bad = [], {}, 0
for plan, src in zip(a.plan, a.src):
    for r in csv.DictReader(open(plan)):
        new = open(r['doc_file'], 'rb').read()
        old = open(os.path.join(src, r['old_metadata_cid'] + '.json'), 'rb').read()
        rev = new
        for nb, ob in back:
            rev = rev.replace(nb, ob)
        why = ''
        if rev != old: why = 'reverse substitution does not reproduce the on-chain doc'
        elif new == old: why = 'new doc is identical to the old one'
        elif CDN_HOST in new: why = 'CDN host still present'
        uris = sorted({s for s in strings(json.loads(new)) if s.startswith('ipfs://')})
        if not why and not uris: why = 'no ipfs:// value in the new doc'
        for u in uris:
            media.setdefault(u.split('?', 1)[0], (r['contract'], r['token_id']))
        bad += bool(why)
        report.append([r['contract'], r['token_id'], r['old_metadata_cid'], 'doc', 'FAIL' if why else 'ok', why])
print(f'A. doc integrity: {len(report)} docs, {bad} failed; {len(media)} distinct ipfs:// media targets')

def get(url, rng=True):
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'metadata-regen/verify-docs', **({'Range': 'bytes=0-65535'} if rng else {})})
            with urllib.request.urlopen(req, timeout=120) as res:
                return res.status, res.read()
        except Exception as e:
            last = e; time.sleep(2 + 2 * attempt)
    return None, str(last).encode()

def probe(item):
    uri, (c, t) = item
    path = uri[len('ipfs://'):]
    status, body = get(a.gateway + path, rng=not path.endswith('/'))
    if status not in (200, 206):
        return [c, t, uri, 'media', 'FAIL', f'gateway {status}: {body[:80].decode("utf-8", "replace")}']
    if path.endswith('/'):
        if b'<' not in body[:2000]:
            return [c, t, uri, 'media', 'FAIL', 'directory URI did not serve an HTML index']
        if CDN_HOST in body:
            return [c, t, uri, 'media', 'FAIL', 'index.html references the CDN host']
        if re.search(rb'(?:src|href)\s*=\s*["\']/(?!/)', body):
            return [c, t, uri, 'media', 'FAIL', 'index.html has root-absolute src/href (breaks under /ipfs/<cid>/)']
    return [c, t, uri, 'media', 'ok', f'{status}, {len(body)} bytes read']

if not a.no_gateway:
    with ThreadPoolExecutor(a.workers) as ex:
        rows = list(ex.map(probe, sorted(media.items())))
    mbad = sum(1 for r in rows if r[4] != 'ok')
    print(f'B. servability: {len(rows)} media targets, {mbad} failed')
    for r in rows:
        if r[4] != 'ok': print(f'  FAIL {r[2]}: {r[5]}')
    report += rows; bad += mbad
else:
    print('B. servability: skipped (--no-gateway)')
with open(a.report, 'w', newline='') as f:
    w = csv.writer(f, lineterminator='\n')
    w.writerow(['contract', 'token_id', 'cid_or_uri', 'check', 'result', 'detail']); w.writerows(report)
print(f'report → {a.report}')
sys.exit(1 if bad else 0)
