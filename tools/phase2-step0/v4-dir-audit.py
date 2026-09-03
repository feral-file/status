#!/usr/bin/env python3
"""Phase-2 Step 0c: audit a V4/V4_2 contract's on-chain metadata directory.

check-base-uri.py (2026-09-02) found both V4-family contracts' live base URI
already points at an IPFS directory (`ipfs://<dirCID>/<tokenId>`), NOT the
feralfile.com API the plan assumed. Consequences this tool measures:

  - the authoritative V4 fix list comes from the docs in that on-chain
    directory (fetched per entry), not from a DB export;
  - the fix ships as ONE `setTokenBaseURI("ipfs://<newDir>/")` tx per
    contract (onlyOwner), so we need exact per-token doc facts first;
  - the census (API-fed) can drift from the chain: the Truth sample's
    on-chain doc is already `ipfs://` while the census says CDN. This tool
    quantifies that drift per token.

For every entry in the directory: fetch the doc via the gateway, record the
doc CID (the gateway's Etag is the terminal element's CID), classify each
media key (`image`, `animation_url`), and cross-check against the step-0a
population (census view).

Usage:
  python3 tools/phase2-step0/v4-dir-audit.py \
      --dir-cid QmQjzvrvZjzNGiqQhTGsiHeTpb9FmEcjCVWxVySf5FANC1 \
      --contract 0xbb12686c360e9057be3cd031140035a705e19cec \
      --population ops/cdn-retirement-phase2/step0/population_tokens.csv \
      --state ops/cdn-retirement-phase2/step0/v4_audit_<name>.state.jsonl \
      --out ops/cdn-retirement-phase2/step0/v4_audit_<name>.csv

Resumable via --state. Gateway default https://ipfs.feralfile.com (prod-02,
NoFetch — success also proves the blocks are locally present there).
"""
import argparse, csv, json, os, re, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

MEDIA_KEYS = ('image', 'animation_url')

ap = argparse.ArgumentParser()
ap.add_argument('--dir-cid', required=True)
ap.add_argument('--contract', required=True)
ap.add_argument('--population', required=True)
ap.add_argument('--state', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--gateway', default='https://ipfs.feralfile.com')
ap.add_argument('--workers', type=int, default=8)
ap.add_argument('--timeout', type=float, default=60)
a = ap.parse_args()

def classify(v):
    if not v: return 'absent'
    if v.startswith('ipfs://'): return 'ipfs'
    if 'cdn.feralfileassets.com' in v or 'imagedelivery.net' in v: return 'cdn'
    if 'ipfs.feralfile.com/ipfs/' in v or 'ipfs.bitmark.com/ipfs/' in v: return 'ff_gateway'
    if v.startswith('data:'): return 'data_uri'
    return 'other'

# --- enumerate the directory from the gateway HTML listing -------------------
print(f'listing {a.dir_cid} via {a.gateway} …', flush=True)
html = urllib.request.urlopen(f'{a.gateway}/ipfs/{a.dir_cid}/', timeout=300).read().decode()
names = sorted(set(re.findall(rf'/ipfs/{a.dir_cid}/(\d+)', html)))
print(f'{len(names)} entries', flush=True)
if not names:
    sys.exit('no numeric entries found in the directory listing')

# --- census view (step-0a population) for the drift cross-check --------------
census_cdn = set()
with open(a.population) as f:
    for r in csv.DictReader(f):
        if r['contract'].lower() == a.contract.lower():
            census_cdn.add(r['token_id'])

# --- fetch every doc (resumable) --------------------------------------------
done = {}
if os.path.exists(a.state):
    for line in open(a.state):
        rec = json.loads(line); done[rec['name']] = rec
pend = [n for n in names if n not in done]
print(f'{len(done)} in state; {len(pend)} to fetch', flush=True)
os.makedirs(os.path.dirname(a.state) or '.', exist_ok=True)
lock = threading.Lock()
sf = open(a.state, 'a')
count = {'n': 0}

def fetch(name):
    rec = {'name': name}
    for attempt in range(3):
        try:
            r = urllib.request.urlopen(f'{a.gateway}/ipfs/{a.dir_cid}/{name}', timeout=a.timeout)
            body = r.read()
            et = r.headers.get('Etag') or ''
            if et.startswith('W/'):
                et = et[2:]
            rec['doc_cid'] = et.strip('"')
            d = json.loads(body)
            for k in MEDIA_KEYS:
                rec[k] = d.get(k, '')
            rec['error'] = ''
            break
        except Exception as e:
            rec['error'] = str(e)[:120]
            time.sleep(5 * (attempt + 1))
    with lock:
        sf.write(json.dumps(rec) + '\n'); sf.flush()
        done[name] = rec; count['n'] += 1
        if rec['error']:
            print(f"[{count['n']}/{len(pend)}] ERROR {name}: {rec['error']}", flush=True)
        elif count['n'] % 250 == 0:
            print(f"[{count['n']}/{len(pend)}] …", flush=True)

with ThreadPoolExecutor(max_workers=a.workers) as ex:
    list(ex.map(fetch, pend))
sf.close()
errs = [n for n in names if done[n].get('error')]
if errs:
    sys.exit(f'{len(errs)} entries failed — rerun to retry them')

# --- report ------------------------------------------------------------------
os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
needs_fix = drift_clean = 0
with open(a.out, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['token_id', 'doc_cid', 'image', 'image_class', 'animation_url',
                'animation_class', 'chain_needs_fix', 'census_says_cdn', 'drift'])
    for n in names:
        d = done[n]
        cls = {k: classify(d.get(k, '')) for k in MEDIA_KEYS}
        fix = any(c == 'cdn' for c in cls.values())
        in_census = n in census_cdn
        drift = 'census_cdn_chain_clean' if (in_census and not fix) else \
                ('chain_cdn_census_clean' if (fix and not in_census) else '')
        needs_fix += fix
        drift_clean += (drift == 'census_cdn_chain_clean')
        w.writerow([n, d.get('doc_cid', ''), d.get('image', ''), cls['image'],
                    d.get('animation_url', ''), cls['animation_url'],
                    fix, in_census, drift])

missing = census_cdn - set(names)
print(f'\n{a.contract} dir {a.dir_cid}: {len(names)} entries')
print(f'  chain_needs_fix (CDN in on-chain doc): {needs_fix}')
print(f'  drift census-says-CDN / chain-already-clean: {drift_clean}')
print(f'  population tokens MISSING from the dir: {len(missing)}' +
      (f' — {sorted(missing)[:5]}…' if missing else ''))
print(f'wrote {a.out}')
