#!/usr/bin/env python3
"""Phase-2 step 3 (V4/V4_2): rebuild a contract's tokenId-named metadata dir,
byte-preserving, media keys only. Built for crystalline work (9,048 docs,
all with CDN media in the on-chain dir — v4_audit_crystalline.csv); generic
over any V4 contract that needs it.

Source of truth: the docs in the CURRENT on-chain directory (fetched raw by
doc CID, cached in --src). Rewrite rule = phase 1 exactly: a media value is
replaced iff it points at the CDN hosts, by swapping its unit prefix for the
`ipfs://<cid>` the unit got in step 1b (query params ride along untouched);
every other byte of the document is preserved. Go-JSON escaping (`&` as
`\\u0026` etc.) is matched in whichever form the document actually uses.

Per-token verification before the file is written:
  - every CDN media value maps to exactly one step-1b unit;
  - the old value occurs in the raw bytes exactly as many times as media
    keys carry it (no accidental hits in description text);
  - the rewritten bytes parse as JSON equal to the original on every key
    except the media keys, whose new values are exactly the mapped ones.
A token failing any check is reported and skipped (exit 1 at the end).

Usage:
  python3 tools/phase2-step3/v4-dir-regen.py \
      --audit ops/cdn-retirement-phase2/step0/v4_audit_crystalline.csv \
      --dir-cids ops/cdn-retirement-phase2/step1/dir_cids.csv \
      --src ops/cdn-retirement-phase2/step3/src \
      --out-dir ops/cdn-retirement-phase2/step3/crystalline-newdir

Then (operator, tunnel open):
  ipfs --api /ip4/127.0.0.1/tcp/5001 add -r --hidden --cid-version 0 -Q <out-dir>
  -> one setTokenBaseURI("ipfs://<newDirCID>/") owner tx (vault)
  -> align artworks.metadata.ipfs_cid to the new per-token doc CIDs
     (`ipfs add -r` without -Q lists them; same WHERE-pinned SQL as Truth)
"""
import argparse, csv, json, os, re, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

CDN_HOSTS = ('cdn.feralfileassets.com', 'imagedelivery.net')
MEDIA_KEYS = ('image', 'animation_url')

ap = argparse.ArgumentParser()
ap.add_argument('--audit', required=True)
ap.add_argument('--dir-cids', required=True)
ap.add_argument('--src', required=True)
ap.add_argument('--out-dir', required=True)
ap.add_argument('--gateway', default='https://ipfs.feralfile.com')
ap.add_argument('--workers', type=int, default=8)
ap.add_argument('--timeout', type=float, default=60)
a = ap.parse_args()
os.makedirs(a.src, exist_ok=True)
os.makedirs(a.out_dir, exist_ok=True)

# unit -> ipfs prefix map from step 1b
dir_map, file_map = {}, {}
for r in csv.DictReader(open(a.dir_cids)):
    if not r['cid']:
        continue
    if r['dir_or_file'].endswith('/'):
        dir_map[r['dir_or_file']] = f"ipfs://{r['cid']}/"
    else:
        file_map[r['dir_or_file']] = f"ipfs://{r['cid']}"


# CDN URL-rewrite fold (measured 2026-09-03): the CDN serves
# generated_images/<name>?variant=<v> from the real key
# generated_images/<v>/<name> (no variant -> 308 to medium). IPFS has no
# such router, so the variant is folded into the path BEFORE prefix
# mapping — the exact byte-verified equivalent of what the CDN serves.
VARIANT_RE = re.compile(r'^(?P<pre>.*/generated_images/)(?P<name>[^/?]+)\?variant=(?P<v>\w+)$')
def fold_variant(v):
    m = VARIANT_RE.match(v)
    return f"{m.group('pre')}{m.group('v')}/{m.group('name')}" if m else v

def map_value(v):
    """CDN URL -> ipfs:// replacement, or None if no unit covers it."""
    if not any(h in v for h in CDN_HOSTS):
        return v  # not a CDN value: unchanged
    v = fold_variant(v)
    base = v.split('?', 1)[0]
    for unit, pref in dir_map.items():
        if v.startswith(unit):
            return pref + v[len(unit):]
    if base in file_map:
        return file_map[base] + v[len(base):]
    return None

def esc(s, raw):
    """Return s in the escaping form the raw bytes actually use."""
    b = s.encode()
    if raw.count(b):
        return b
    for ch, rep in (('&', '\\u0026'), ('<', '\\u003c'), ('>', '\\u003e')):
        s = s.replace(ch, rep)
    return s.encode()

audit = [r for r in csv.DictReader(open(a.audit)) if r['chain_needs_fix'] == 'True']
print(f'{len(audit)} tokens to regenerate', flush=True)
lock = threading.Lock()
stats = {'done': 0, 'skipped': 0}
failures = []

def fetch_raw(cid):
    p = os.path.join(a.src, cid)
    if os.path.exists(p):
        return open(p, 'rb').read()
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(f'{a.gateway}/ipfs/{cid}', timeout=a.timeout).read()
            with open(p, 'wb') as f:
                f.write(raw)
            return raw
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))

def process(r):
    t, cid = r['token_id'], r['doc_cid']
    out_p = os.path.join(a.out_dir, t)
    fail = None
    try:
        if os.path.exists(out_p):
            with lock:
                stats['skipped'] += 1
            return
        raw = fetch_raw(cid)
        doc = json.loads(raw)
        # plan the replacements
        repl = {}   # old_value -> (new_value, n_media_keys_carrying_it)
        for k in MEDIA_KEYS:
            v = doc.get(k)
            if v and any(h in v for h in CDN_HOSTS):
                nv = map_value(v)
                if nv is None:
                    fail = f'no step-1b unit covers {k}={v[:90]}'
                    break
                old = repl.get(v)
                repl[v] = (nv, (old[1] + 1) if old else 1)
        if fail is None and not repl:
            fail = 'chain_needs_fix but no CDN media value found'
        new_raw = raw
        if fail is None:
            for old_v, (new_v, n) in repl.items():
                ob, nb = esc(old_v, raw), esc(new_v, raw)
                cnt = new_raw.count(ob)
                if cnt != n:
                    fail = f'value occurs {cnt}× in bytes but {n}× in media keys: {old_v[:80]}'
                    break
                new_raw = new_raw.replace(ob, nb)
        if fail is None:
            new_doc = json.loads(new_raw)
            for k in set(doc) | set(new_doc):
                if k in MEDIA_KEYS:
                    exp = repl.get(doc.get(k), (doc.get(k),))[0]
                    if new_doc.get(k) != exp:
                        fail = f'{k} rewrote to unexpected value'
                        break
                elif doc.get(k) != new_doc.get(k):
                    fail = f'non-media key changed: {k}'
                    break
        if fail is None:
            with open(out_p, 'wb') as f:
                f.write(new_raw)
    except Exception as e:
        fail = f'{type(e).__name__}: {str(e)[:120]}'
    with lock:
        if fail:
            failures.append((t, cid, fail))
            print(f'FAIL {t}: {fail}', flush=True)
        else:
            stats['done'] += 1
            if stats['done'] % 500 == 0:
                print(f"[{stats['done']}/{len(audit)}] …", flush=True)

with ThreadPoolExecutor(max_workers=a.workers) as ex:
    list(ex.map(process, audit))

with open(os.path.join(os.path.dirname(a.out_dir.rstrip('/')), 'regen_failures.csv'), 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['token_id', 'doc_cid', 'reason'])
    w.writerows(failures)
n_out = len(os.listdir(a.out_dir))
print(f'\nregen: {stats["done"]} written (+{stats["skipped"]} already present), '
      f'{len(failures)} failed; out-dir now holds {n_out}/{len(audit)} docs')
print('next: ipfs add -r --hidden --cid-version 0 (tunnel) -> one setTokenBaseURI tx -> DB align')
if failures:
    sys.exit(1)
