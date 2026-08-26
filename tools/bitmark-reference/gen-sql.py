#!/usr/bin/env python3
"""Reference phase for the Bitmark-era works: emit ipfs_reference rows that
map each work's CDN preview path to its byte-verified copy inside the pinned
series directory, so the server's metadata generators (swap mint, Tezos
mint/refresh, OpenSea refresh) produce ipfs:// URIs when these works migrate.

  python3 gen-sql.py [--enumeration data/bitmark_enumeration_<date>.csv]
                     [--pin-manifest data/pin_manifest_<date>.csv]
                     [--verify N]        # HEAD N random targets via ipfs.feralfile.com first
                     > bitmark-reference.sql

How the path is derived: tools/pin_works.sh syncs s3://…/previews/<sid>/ to
<work>/previews/ and s3://…/artworks/<sid>/ to <work>/artworks/, then adds
<work> as one directory CID. A CDN key previews/<sid>/<ts>/preview.mp4 is
therefore ipfs://<seriesCid>/previews/<ts>/preview.mp4 — the <sid> segment
drops out. --verify checks that against the gateway before you trust the
SQL; run it only after the series are pinned on prod-02 (Gateway.NoFetch).

Software works carry a query (previews/<sid>/<ts>/?edition_number=N&…).
The server's own convention (internal/tasks/ipfs.go ensureIPFSReferenceForURI)
stores TWO rows for those: the path alone → ipfs://<cid>/<path>, and the
full uri → ipfs://<cid>/<path>?<query>. The generator does the same, so the
rows are indistinguishable from ones the server would have written.

What it does NOT touch: thumbnails (imagedelivery.net, not in the archive),
artworks.preview_uri itself (still the CDN path — the site keeps playing
from the CDN; ipfs_reference is the layer the on-chain metadata is built
from), and any DB row for works already migrated off Bitmark.
"""
import argparse, csv, glob, os, random, sys, urllib.request, collections
root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
ap = argparse.ArgumentParser()
ap.add_argument('--enumeration'); ap.add_argument('--pin-manifest'); ap.add_argument('--verify', type=int, default=0)
ap.add_argument('--gateway', default='https://ipfs.feralfile.com/ipfs/')
a = ap.parse_args()
enum = a.enumeration or sorted(glob.glob(os.path.join(root, 'data/bitmark_enumeration_*.csv')))[-1]
pinm = a.pin_manifest or sorted(glob.glob(os.path.join(root, 'data/pin_manifest_*.csv')))[-1]
cid_of = {r['series_id']: r['cid'] for r in csv.DictReader(open(pinm))}
works = [r for r in csv.DictReader(open(enum)) if r['state'] == 'still_bitmark']
refs = {}  # preview_uri -> (ipfs_uri, series_id)
missing = collections.Counter(); skipped = 0
for w in works:
    p = w['preview_uri']
    if not p.startswith('previews/'): skipped += 1; continue
    sid = w['series_id']
    if sid not in cid_of: missing[sid] += 1; continue
    path, _, query = p.partition('?')
    parts = path.split('/')         # previews/<sid>/<ts>/preview.ext  or  previews/<sid>/<ts>/
    if len(parts) < 4 or parts[1] != sid: skipped += 1; continue
    base = f"ipfs://{cid_of[sid]}/previews/{'/'.join(parts[2:])}"
    refs[path] = (base, sid)                       # path-only row (always)
    if query: refs[p] = (f"{base}?{query}", sid)   # full row with the query, server convention
print(f'-- {len(works)} still-Bitmark works from {os.path.basename(enum)}; {len(refs)} ipfs_reference rows ({sum(1 for k in refs if chr(63) not in k)} path-only, {sum(1 for k in refs if chr(63) in k)} with query); '
      f'{skipped} skipped (non-preview path); series without a pin: {dict(missing) or "none"}', file=sys.stderr)
if a.verify:
    sample = random.sample(sorted((k, v) for k, v in refs.items() if '?' not in k), min(a.verify, len(refs)))
    bad = 0
    for p, (u, sid) in sample:
        url = a.gateway.rstrip('/') + '/' + u[len('ipfs://'):]
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=120) as r: st = f'{r.status} {r.headers.get("Content-Type","")[:20]}'
        except Exception as e: st = f'FAIL {getattr(e, "code", type(e).__name__)}'; bad += 1
        print(f'   verify {st:28} {u[:80]}', file=sys.stderr)
    if bad: sys.exit(f'{bad}/{len(sample)} sample targets did not resolve — pin the series on prod-02 first, or the path shape is wrong')
    print(f'-- verified {len(sample)} random targets on {a.gateway}', file=sys.stderr)
print('-- Bitmark-era reference phase: map CDN preview paths to their archived IPFS copies (feral-file#3435)')
print('-- Idempotent: ON CONFLICT updates ipfs_uri. Run inside a transaction and compare counts before COMMIT.')
print('BEGIN;')
print(f"SELECT count(*) AS existing FROM ipfs_reference WHERE uri IN ({','.join(chr(39)+p+chr(39) for p in sorted(refs))});")
print('INSERT INTO ipfs_reference (uri, ipfs_uri, created_at, updated_at) VALUES')
vals = [f"  ('{p}', '{u}', now(), now())" for p, (u, sid) in sorted(refs.items())]
print(',\n'.join(vals))
print('ON CONFLICT (uri) DO UPDATE SET ipfs_uri = EXCLUDED.ipfs_uri, updated_at = now();')
print(f'-- expect INSERT 0 {len(refs)}')
print('-- COMMIT;  -- after review')
