#!/usr/bin/env python3
"""Phase-2 step 3 (V3): regenerate the 2,341 V3 token metadata docs,
byte-preserving, media keys only.

V3 tokenURI = <gateway><docCID> — each token's metadata is a single FILE
(no directory, no /metadata.json). Fix = new doc file per token → pin →
`updateArtworkEditionIPFSCid(tokenId, newCid)` via tools/update-token-uri
(docSuffix "" configs).

Rewrite rule (phase-1 + the step-0 finding):
  - a media value is replaced iff it points at the CDN hosts — as a full
    URL (`https://cdn.feralfileassets.com/…`, `imagedelivery.net`) OR as a
    RELATIVE path (`previews/…` / `thumbnails/…`, no scheme — 590 tokens
    carry these on chain; the API masks them with the CDN host);
  - the replacement swaps the unit prefix for the unit's step-1b
    `ipfs://<cid>`, query params ride along byte-identically;
  - every other byte of the doc is preserved (Go-JSON escaping matched;
    occurrence-count check prevents accidental hits in prose).

Inputs: step-0 v3_audit.csv (onchain_cid per token) + step-1b dir_cids.csv.
Outputs: --out-dir/<contract>/<token_id>.json + plan.csv
(contract, edition, token_id, token_id_db, old_metadata_cid, doc_file) —
pin-docs.py turns plan.csv into per-contract updates CSVs with new CIDs.

  python3 tools/phase2-step3/v3-doc-regen.py \
      --audit ops/cdn-retirement-phase2/step0/v3_audit.csv \
      --dir-cids ops/cdn-retirement-phase2/step1/dir_cids.csv \
      --src ops/cdn-retirement-phase2/step3/v3-src \
      --out-dir ops/cdn-retirement-phase2/step3/v3-docs
"""
import argparse, csv, json, os, re, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

CDN_HOSTS = ('cdn.feralfileassets.com', 'imagedelivery.net')
CDN_PREFIX = 'https://cdn.feralfileassets.com/'
MEDIA_KEYS = ('image', 'animation_url')
GATEWAYS = ['https://ipfs.feralfile.com/ipfs/', 'https://ipfs.bitmark.com/ipfs/', 'https://ipfs.io/ipfs/']

ap = argparse.ArgumentParser()
ap.add_argument('--audit', required=True)
ap.add_argument('--dir-cids', required=True)
ap.add_argument('--src', required=True)
ap.add_argument('--out-dir', required=True)
ap.add_argument('--workers', type=int, default=8)
ap.add_argument('--timeout', type=float, default=60)
a = ap.parse_args()
os.makedirs(a.src, exist_ok=True)

# step-1b unit -> ipfs prefix maps, keyed BOTH by full URL and by host-relative path
dir_map, file_map = {}, {}
for r in csv.DictReader(open(a.dir_cids)):
    if not r['cid']:
        continue
    unit, ipfs = r['dir_or_file'], f"ipfs://{r['cid']}"
    keys = [unit]
    if unit.startswith(CDN_PREFIX):
        keys.append(unit[len(CDN_PREFIX):])          # relative form
    for k in keys:
        if unit.endswith('/'):
            dir_map[k] = ipfs + '/'
        else:
            file_map[k] = ipfs

def is_cdn(v):
    return v and (any(h in v for h in CDN_HOSTS)
                  or v.startswith(('previews/', 'thumbnails/')))


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
    v = fold_variant(v)
    base = v.split('?', 1)[0]
    for unit, pref in dir_map.items():
        if v.startswith(unit):
            return pref + v[len(unit):]
    if base in file_map:
        return file_map[base] + v[len(base):]
    return None

def esc(s, raw):
    b = s.encode()
    if raw.count(b):
        return b
    for ch, rep in (('&', '\\u0026'), ('<', '\\u003c'), ('>', '\\u003e')):
        s = s.replace(ch, rep)
    return s.encode()

def fetch_raw(cid):
    p = os.path.join(a.src, cid + '.json')
    if os.path.exists(p):
        return open(p, 'rb').read()
    last = None
    for g in GATEWAYS:
        for attempt in range(2):
            try:
                raw = urllib.request.urlopen(g + cid, timeout=a.timeout).read()
                json.loads(raw)          # must be the doc, not an error page
                with open(p, 'wb') as f:
                    f.write(raw)
                return raw
            except Exception as e:
                last = e
                time.sleep(2)
    raise RuntimeError(f'fetch failed on all gateways: {last}')

audit = [r for r in csv.DictReader(open(a.audit)) if r['needs_fix'] == '1']
print(f'{len(audit)} tokens to regenerate', flush=True)
lock = threading.Lock()
plan, failures = [], []
stats = {'done': 0, 'skipped': 0}

def process(r):
    c, t, cid = r['contract'], r['token_id'], r['onchain_cid']
    out_p = os.path.join(a.out_dir, c, t + '.json')
    fail = None
    edition = ''
    try:
        raw = fetch_raw(cid)
        doc = json.loads(raw)
        edition = str(doc.get('edition_index', ''))
        if edition == '':
            m = str(doc.get('name', ''))
            edition = (m.rsplit('#', 1)[1].strip() if '#' in m else '')
        repl = {}
        for k in MEDIA_KEYS:
            v = doc.get(k)
            if v and is_cdn(v):
                nv = map_value(v)
                if nv is None:
                    fail = f'no step-1b unit covers {k}={v[:90]}'
                    break
                old = repl.get(v)
                repl[v] = (nv, (old[1] + 1) if old else 1)
        if fail is None and not repl:
            fail = 'needs_fix but no CDN media value found'
        new_raw = raw
        if fail is None:
            for old_v, (new_v, n) in repl.items():
                ob, nb = esc(old_v, raw), esc(new_v, raw)
                cnt = new_raw.count(ob)
                if cnt != n:
                    fail = f'value occurs {cnt}x in bytes but {n}x in media keys: {old_v[:80]}'
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
            os.makedirs(os.path.dirname(out_p), exist_ok=True)
            with open(out_p, 'wb') as f:
                f.write(new_raw)
    except Exception as e:
        fail = f'{type(e).__name__}: {str(e)[:120]}'
    with lock:
        if fail:
            failures.append((c, t, cid, fail))
            print(f'FAIL {c[:10]} …{t[-8:]}: {fail}', flush=True)
        else:
            plan.append([c, edition, t, r['token_id_db'], cid, out_p])
            stats['done'] += 1
            if stats['done'] % 250 == 0:
                print(f"[{stats['done']}/{len(audit)}] …", flush=True)

with ThreadPoolExecutor(max_workers=a.workers) as ex:
    list(ex.map(process, audit))

os.makedirs(a.out_dir, exist_ok=True)
with open(os.path.join(a.out_dir, 'plan.csv'), 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['contract', 'edition', 'token_id', 'token_id_db', 'old_metadata_cid', 'doc_file'])
    w.writerows(sorted(plan))
with open(os.path.join(a.out_dir, 'regen_failures.csv'), 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['contract', 'token_id', 'onchain_cid', 'reason'])
    w.writerows(failures)
print(f'\nregen: {stats["done"]} docs written, {len(failures)} failed -> plan.csv / regen_failures.csv')
print('next: pin-docs.py uploads + pins the docs and emits per-contract updates CSVs')
if failures:
    sys.exit(1)
