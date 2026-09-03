#!/usr/bin/env python3
"""Chain-side audit of FeralfileExhibitionV2/V3 token metadata.

For every (contract, token_id) in the input csv: read tokenURI() on-chain
(JSON-RPC batch eth_call), fetch the metadata doc (cached in src/), and
classify `animation_url` and `image`. Both on-chain shapes are handled:
V2 tokenURI = <base><dirCID>/metadata.json; V3 tokenURI = <base><docCID>
(bare file CID, no suffix — phase-2 step 0, 2026-09-02). The chain is
authoritative — the feralfile.com API overlays alternativePreviewURI and
rewrites ipfs:// URIs, so census/API output must not be used to build a fix
list.

  RPC_URL=https://… python3 audit.py tokens.csv [--db-export export.csv] [--out audit.csv] [--workers 16]

Input csv: any file with `contract` and `token_id` columns (e.g. the DB export
from db/export-v2-cdn-tokens.sql, or ops/…/migrated_bitmark_works_media_hosting_*.csv).
--db-export: csv with contract,token_id,old_metadata_cid — the on-chain cid is
compared against it (column db_cid_match).

Output audit.csv, one row per token:
  contract,token_id,token_id_db,onchain_cid,token_base_uri,animation_url,image,anim_class,image_class,needs_fix,legacy_format,db_cid,db_cid_match,error
  *_class: ipfs | cdn | imagedelivery | other | none
  needs_fix = 1 if animation_url or image is present and not ipfs://
Also contracts.csv: contract,trustee,owner,token_base_uri,tokens,needs_fix.
Re-runnable: metadata fetches are cached by cid; chain reads are always live.
"""
import argparse, csv, json, os, re, sys, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

SEL_TOKEN_URI, SEL_TRUSTEE, SEL_OWNER = '0xc87b56dd', '0xfdf97cb2', '0x8da5cb5b'
GATEWAY_FALLBACKS = ['https://ipfs.bitmark.com/ipfs/', 'https://ipfs.io/ipfs/']

ap = argparse.ArgumentParser()
ap.add_argument('tokens')
ap.add_argument('--db-export')
ap.add_argument('--out', default='audit.csv')
ap.add_argument('--workers', type=int, default=16)
ap.add_argument('--batch', type=int, default=20, help='eth_calls per JSON-RPC batch')
ap.add_argument('--rps', type=float, default=20, help='eth_calls per second (Infura: eth_call = 80 credits; Developer 2000 cps → 25/s, Team 5000 cps → 62/s)')
a = ap.parse_args()
RPC = os.environ.get('RPC_URL') or sys.exit('RPC_URL is required (use a paid RPC; public ones rate-limit)')
here = os.path.dirname(os.path.abspath(__file__)); os.makedirs(os.path.join(here, 'src'), exist_ok=True)

class Pacer:
    """Token-bucket style pacing on eth_calls/second; halves the rate on every
    rate-limit response and creeps back up after clean batches."""
    def __init__(self, rps): self.rps = self.max = rps; self.next = time.monotonic()
    def wait(self, n):
        now = time.monotonic(); time.sleep(max(0, self.next - now)); self.next = max(now, self.next) + n / self.rps
    def limited(self): self.rps = max(1, self.rps / 2); print(f'\n  rate limited → {self.rps:.1f} calls/s', file=sys.stderr)
    def clean(self): self.rps = min(self.max, self.rps * 1.05)
pacer = Pacer(a.rps)

def rate_limited_error(e):  # JSON-RPC error object
    return e and (e.get('code') in (-32005, 429) or 'rate' in str(e.get('message', '')).lower() or 'too many' in str(e.get('message', '')).lower())

def rpc_batch(calls):
    body = [{'jsonrpc': '2.0', 'id': i, 'method': 'eth_call', 'params': [{'to': to, 'data': data}, 'latest']} for i, (to, data) in enumerate(calls)]
    last = None
    for attempt in range(8):
        pacer.wait(len(calls))
        try:
            req = urllib.request.Request(RPC, json.dumps(body).encode(), {'Content-Type': 'application/json', 'User-Agent': 'metadata-regen/audit'})
            res = json.load(urllib.request.urlopen(req, timeout=60))
            items = res if isinstance(res, list) else [res]
            if any(rate_limited_error(r.get('error')) for r in items): pacer.limited(); time.sleep(1 + attempt); continue
            out = [None] * len(calls)
            for r in items: out[r['id']] = r.get('result') or ('ERR:' + json.dumps(r.get('error')))
            pacer.clean(); return out
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429: pacer.limited(); time.sleep(float(e.headers.get('Retry-After') or 1 + attempt)); continue
            time.sleep(2 ** attempt)
        except Exception as e:
            last = e; time.sleep(2 ** attempt)
    return ['ERR:' + str(last)] * len(calls)

def abi_string(hexdata):
    if not hexdata or hexdata.startswith('ERR:') or hexdata == '0x': return None
    b = bytes.fromhex(hexdata[2:]); off = int.from_bytes(b[:32], 'big'); ln = int.from_bytes(b[off:off+32], 'big')
    return b[off+32:off+32+ln].decode('utf-8', 'replace')

CID_RE = re.compile(r'^(Qm[1-9A-HJ-NP-Za-km-z]{44}|baf[a-z0-9]{20,})$')

def cid_from_uri(uri):
    """Returns (cid, doc_suffix). V2: <base><cid>/metadata.json (dir CID, doc
    at /metadata.json). V3: <base><cid> — the bare doc CID, no suffix
    (verified on chain 2026-09-02, all six V3 contracts)."""
    p = uri.rstrip('/').split('/')
    if p[-1] == 'metadata.json' and len(p) >= 2:
        return p[-2], '/metadata.json'
    if CID_RE.match(p[-1]):
        return p[-1], ''
    return None, None

def classify(u):
    if u in (None, ''): return 'none'
    if u.startswith('ipfs://'): return 'ipfs'
    h = urllib.parse.urlparse(u).netloc
    if h.endswith('feralfileassets.com'): return 'cdn'
    if h == 'imagedelivery.net': return 'imagedelivery'
    return 'other'

def fetch_metadata(base, cid, suffix='/metadata.json'):
    p = os.path.join(here, 'src', cid + '.json')
    if os.path.exists(p): return json.load(open(p)), None
    last = None
    for g in ([base] if base else []) + GATEWAY_FALLBACKS:
        try:
            raw = urllib.request.urlopen(urllib.request.Request(f'{g}{cid}{suffix}', headers={'User-Agent': 'metadata-regen/audit'}), timeout=120).read()
            m = json.loads(raw); open(p, 'wb').write(raw); return m, None
        except Exception as e: last = e
    return None, f'fetch failed: {last}'

rows = [r for r in csv.DictReader(open(a.tokens))]
if not rows or 'contract' not in rows[0] or 'token_id' not in rows[0]: sys.exit('input needs contract,token_id columns')
def norm_id(t):
    """swaps.token is decimal in most rows but some older swaps stored the same
    uint256 as 64-char hex (verified on chain 2026-08-28: identical token). Chain
    calls use the decimal form; the DB form is kept as token_id_db for SQL."""
    t = t.strip()
    if t.isdigit(): return t
    if re.fullmatch(r'(0x)?[0-9a-fA-F]{64}', t): return str(int(t, 16))
    return None
dbform = {}
for r in rows:
    n = norm_id(r['token_id'])
    if n: dbform[(r['contract'].lower(), n)] = r['token_id'].strip()
toks = sorted(dbform)
malformed = [dict(contract=r['contract'].lower(), token_id=r['token_id'], token_id_db=r['token_id'], error='token_id is neither decimal nor 64-hex') for r in rows if not norm_id(r['token_id'])]
if malformed: print(f'{len(malformed)} malformed token_id rows skipped (recorded as errors)', file=sys.stderr)
db = {}
if a.db_export:
    for r in csv.DictReader(open(a.db_export)):
        n = norm_id(r['token_id'])
        if n: db[(r['contract'].lower(), n)] = r['old_metadata_cid']
print(f'{len(toks)} tokens on {len({c for c,_ in toks})} contracts', file=sys.stderr)

# contracts: trustee / owner
contracts = sorted({c for c, _ in toks})
meta_c = {}
res = rpc_batch([(c, SEL_TRUSTEE) for c in contracts] + [(c, SEL_OWNER) for c in contracts])
for i, c in enumerate(contracts):
    t, o = res[i], res[len(contracts) + i]
    meta_c[c] = {'trustee': '0x' + t[-40:] if t and not t.startswith('ERR') else '', 'owner': '0x' + o[-40:] if o and not o.startswith('ERR') else ''}

# tokenURI, batched
uris = {}
for i in range(0, len(toks), a.batch):
    chunk = toks[i:i+a.batch]
    for (c, t), r in zip(chunk, rpc_batch([(c, SEL_TOKEN_URI + int(t).to_bytes(32, 'big').hex()) for c, t in chunk])):
        uris[(c, t)] = r
    print(f'  tokenURI {min(i+a.batch, len(toks))}/{len(toks)}  ({pacer.rps:.0f} calls/s)', file=sys.stderr, end='\r')
print(file=sys.stderr)

def work(key):
    c, t = key; raw = uris[key]
    if raw is None or raw.startswith('ERR'): return dict(contract=c, token_id=t, token_id_db=dbform[key], error=raw or 'no result')
    uri = abi_string(raw); cid, suffix = cid_from_uri(uri or '')
    if not cid: return dict(contract=c, token_id=t, error=f'unexpected tokenURI {uri!r}')
    base = uri[:uri.index(cid)]
    m, err = fetch_metadata(base if base.startswith('http') else None, cid, suffix)
    row = dict(contract=c, token_id=t, token_id_db=dbform[key], onchain_cid=cid, token_base_uri=base, error=err or '')
    if m:
        an, im = m.get('animation_url'), m.get('image')
        row.update(animation_url=an or '', image=im or '', anim_class=classify(an), image_class=classify(im))
        row['needs_fix'] = int(any(x not in ('ipfs', 'none') for x in (row['anim_class'], row['image_class'])))
        row['legacy_format'] = int(str(m.get('edition_index', '')) == '')  # 2021 swaps: 6-key metadata, edition only in name "#N"
    if key in db: row['db_cid'] = db[key]; row['db_cid_match'] = int(db[key] == cid)
    return row

cols = 'contract,token_id,token_id_db,onchain_cid,token_base_uri,animation_url,image,anim_class,image_class,needs_fix,legacy_format,db_cid,db_cid_match,error'.split(',')
with ThreadPoolExecutor(a.workers) as ex: out = list(ex.map(work, toks)) + malformed
with open(a.out, 'w') as f:
    w = csv.DictWriter(f, cols, extrasaction='ignore', lineterminator='\n'); w.writeheader(); w.writerows(out)
with open(os.path.splitext(a.out)[0] + '.contracts.csv', 'w') as f:
    w = csv.writer(f, lineterminator='\n'); w.writerow(['contract', 'trustee', 'owner', 'token_base_uri', 'tokens', 'needs_fix', 'errors'])
    for c in contracts:
        rs = [r for r in out if r['contract'] == c]
        bases = {r.get('token_base_uri') for r in rs if r.get('token_base_uri')}
        w.writerow([c, meta_c[c]['trustee'], meta_c[c]['owner'], '|'.join(sorted(bases)), len(rs), sum(r.get('needs_fix', 0) or 0 for r in rs), sum(1 for r in rs if r.get('error'))])
fix = sum(r.get('needs_fix', 0) or 0 for r in out); errs = sum(1 for r in out if r.get('error'))
mism = sum(1 for r in out if r.get('db_cid_match') == 0)
print(f'{len(out)} tokens: needs_fix {fix}, errors {errs}, db_cid mismatches {mism} → {a.out}, {os.path.splitext(a.out)[0]}.contracts.csv', file=sys.stderr)
sys.exit(1 if errs else 0)
