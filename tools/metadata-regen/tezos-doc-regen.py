#!/usr/bin/env python3
"""Tezos (FA2, FeralfileExhibitionV2): audit and regenerate TZIP-21 token
metadata docs whose media point at the CDN — byte-preserving, URI fields only.

Each token's `token_info[""]` is `ipfs://<docCID>`, one JSON FILE per token
(no directory). The doc names its media in `artifactUri`, `displayUri`,
`thumbnailUri`, `image` and every `formats[].uri`. Fix = new doc per token →
pin (`pin-docs.py`) → trustee batches via `tools/update-tezos-metadata`.

Rewrite rule (the V3 rule of `v3-doc-regen.py`, applied to the TZIP-21 fields):
  - a URI field is replaced iff it is a `https://cdn.feralfileassets.com/…` URL;
  - the pin-unit prefix is swapped for the unit's `ipfs://<cid>` from the
    registry (`dir_cids.csv`, written by `tools/ipfs-mirror`); the rest of the
    value — sub-path and query (`?contract=…&token_id=…&blockchain=tezos`) —
    rides along byte-identically;
  - every other byte of the doc is preserved: the swap is done on the raw
    bytes, the number of byte hits must equal the number of fields that carry
    the unit, and the parsed result must equal the parsed source with exactly
    those fields mapped. No CDN host may remain anywhere in the new doc.

  # 1 · audit only (no registry needed): which tokens, which CDN URLs
  python3 tools/metadata-regen/tezos-doc-regen.py --tokens tokens.csv --src src --audit-only --audit-out tezos_audit.csv

  # 2 · regenerate, once the units are mirrored
  python3 tools/metadata-regen/tezos-doc-regen.py --tokens tokens.csv --src src \
      --dir-cids dir_cids.csv --out-dir tezos-docs --audit-out tezos_audit.csv

--tokens: `contract,token_id,token_uri` (tools/contract-audit/enumerate-tokens.py);
only KT1… rows are read. Outputs: tezos_audit.csv (contract, token_id,
onchain_cid, edition, needs_fix, cdn_urls, other_urls, error),
<out-dir>/<contract>/<token_id>.json, <out-dir>/plan.csv (pin-docs.py input)
and <out-dir>/regen_failures.csv. Exit 1 on any failure.
"""
import argparse, csv, json, os, re, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

CDN_HOST = 'cdn.feralfileassets.com'
CDN_PREFIX = f'https://{CDN_HOST}/'
URI_KEYS = ('artifactUri', 'displayUri', 'thumbnailUri', 'image')
GATEWAYS = ['https://ipfs.feralfile.com/ipfs/', 'https://ipfs.bitmark.com/ipfs/', 'https://ipfs.io/ipfs/']
CID_RE = re.compile(r'^ipfs://(Qm[1-9A-HJ-NP-Za-km-z]{44}|baf[a-z0-9]{20,})$')

ap = argparse.ArgumentParser()
ap.add_argument('--tokens', required=True)
ap.add_argument('--src', required=True, help='cache dir for the fetched source docs')
ap.add_argument('--dir-cids', help='pin-unit registry (required unless --audit-only)')
ap.add_argument('--out-dir')
ap.add_argument('--audit-out', default='tezos_audit.csv')
ap.add_argument('--audit-only', action='store_true')
ap.add_argument('--workers', type=int, default=8)
ap.add_argument('--timeout', type=float, default=60)
a = ap.parse_args()
if not a.audit_only and not (a.dir_cids and a.out_dir):
    sys.exit('--dir-cids and --out-dir are required unless --audit-only')
os.makedirs(a.src, exist_ok=True)

dir_map, file_map = {}, {}
if a.dir_cids:
    for r in csv.DictReader(open(a.dir_cids)):
        if not r['cid']:
            continue
        if r['dir_or_file'].endswith('/'):
            dir_map[r['dir_or_file']] = f"ipfs://{r['cid']}/"
        else:
            file_map[r['dir_or_file']] = f"ipfs://{r['cid']}"

def unit_of(v):
    """(unit, replacement prefix) covering a CDN URL, or (None, None)."""
    for unit, pref in dir_map.items():
        if v.startswith(unit):
            return unit, pref
    base = v.split('?', 1)[0]
    if base in file_map:
        return base, file_map[base]
    return None, None

def uri_fields(doc):
    """Every media URI in the doc as (label, value)."""
    out = [(k, doc[k]) for k in URI_KEYS if isinstance(doc.get(k), str)]
    for i, f in enumerate(doc.get('formats') or []):
        if isinstance(f, dict) and isinstance(f.get('uri'), str):
            out.append((f'formats[{i}].uri', f['uri']))
    return out

def mapped_doc(doc, mapping):
    d = json.loads(json.dumps(doc))
    for k in URI_KEYS:
        if isinstance(d.get(k), str):
            d[k] = mapping.get(d[k], d[k])
    for f in d.get('formats') or []:
        if isinstance(f, dict) and isinstance(f.get('uri'), str):
            f['uri'] = mapping.get(f['uri'], f['uri'])
    return d

def fetch_raw(cid):
    p = os.path.join(a.src, cid + '.json')
    if os.path.exists(p):
        return open(p, 'rb').read()
    last = None
    for attempt in range(3):
        for g in GATEWAYS:
            try:
                raw = urllib.request.urlopen(urllib.request.Request(g + cid, headers={'User-Agent': 'metadata-regen/tezos-doc-regen'}), timeout=a.timeout).read()
                json.loads(raw)          # must be the doc, not an error page
                with open(p, 'wb') as f:
                    f.write(raw)
                return raw
            except Exception as e:
                last = e
        time.sleep(2)
    raise RuntimeError(f'fetch failed on all gateways: {last}')

tokens = [r for r in csv.DictReader(open(a.tokens)) if r['contract'].startswith('KT1')]
print(f'{len(tokens)} Tezos tokens on {len({r["contract"] for r in tokens})} contracts', flush=True)
lock = threading.Lock()
audit, plan, failures = [], [], []

def process(r):
    c, t = r['contract'], r['token_id']
    row = dict(contract=c, token_id=t, onchain_cid='', edition='', needs_fix='', cdn_urls='', other_urls='', error='')
    fail, plan_row = None, None
    try:
        m = CID_RE.match(r['token_uri'])
        if not m:
            raise ValueError(f'token_uri is not ipfs://<cid>: {r["token_uri"][:60]!r}')
        cid = row['onchain_cid'] = m.group(1)
        raw = fetch_raw(cid)
        doc = json.loads(raw)
        row['edition'] = str(doc.get('editionIndex', ''))
        fields = uri_fields(doc)
        cdn = [v for _, v in fields if v.startswith(CDN_PREFIX)]
        row['cdn_urls'] = ';'.join(sorted(set(cdn)))
        row['other_urls'] = ';'.join(sorted({v for _, v in fields if not v.startswith(CDN_PREFIX) and not v.startswith('ipfs://')}))
        row['needs_fix'] = int(bool(cdn))
        if not cdn and CDN_HOST.encode() in raw:
            fail = 'CDN host appears outside the URI fields'
        if cdn and not a.audit_only and fail is None:
            per_unit, mapping = {}, {}
            for v in cdn:
                unit, pref = unit_of(v)
                if unit is None:
                    fail = f'no pin unit covers {v[:100]}'
                    break
                per_unit.setdefault(unit, [pref, 0])[1] += 1
                mapping[v] = pref + v[len(unit):]
            new_raw = raw
            if fail is None:
                for unit, (pref, n) in per_unit.items():
                    hits = raw.count(unit.encode())
                    if hits != n:
                        fail = f'unit occurs {hits}x in the bytes but in {n} URI fields: {unit}'
                        break
                    new_raw = new_raw.replace(unit.encode(), pref.encode())
            if fail is None and json.loads(new_raw) != mapped_doc(doc, mapping):
                fail = 'rewritten doc differs from the source outside the mapped URI fields'
            if fail is None and CDN_HOST.encode() in new_raw:
                fail = 'CDN host still present after the rewrite'
            if fail is None and not row['edition']:
                fail = 'doc has no editionIndex'
            if fail is None:
                out_p = os.path.join(a.out_dir, c, t + '.json')
                os.makedirs(os.path.dirname(out_p), exist_ok=True)
                with open(out_p, 'wb') as f:
                    f.write(new_raw)
                plan_row = [c, row['edition'], t, t, cid, out_p]
    except Exception as e:
        fail = f'{type(e).__name__}: {str(e)[:140]}'
    row['error'] = fail or ''
    with lock:
        audit.append(row)
        if fail:
            failures.append((c, t, row['onchain_cid'], fail))
            print(f'FAIL {c[:10]} …{t[-8:]}: {fail}', flush=True)
        elif plan_row:
            plan.append(plan_row)
        if len(audit) % 500 == 0:
            print(f'[{len(audit)}/{len(tokens)}] …', flush=True)

with ThreadPoolExecutor(max_workers=a.workers) as ex:
    list(ex.map(process, tokens))

cols = ['contract', 'token_id', 'onchain_cid', 'edition', 'needs_fix', 'cdn_urls', 'other_urls', 'error']
with open(a.audit_out, 'w', newline='') as f:
    w = csv.DictWriter(f, cols, lineterminator='\n'); w.writeheader()
    w.writerows(sorted(audit, key=lambda r: (r['contract'], int(r['token_id']))))
need = sum(1 for r in audit if r['needs_fix'] == 1)
print(f'\naudit: {len(audit)} tokens, needs_fix {need}, errors {len(failures)} → {a.audit_out}')
if not a.audit_only:
    os.makedirs(a.out_dir, exist_ok=True)
    with open(os.path.join(a.out_dir, 'plan.csv'), 'w', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(['contract', 'edition', 'token_id', 'token_id_db', 'old_metadata_cid', 'doc_file'])
        w.writerows(sorted(plan, key=lambda r: (r[0], int(r[2]))))
    with open(os.path.join(a.out_dir, 'regen_failures.csv'), 'w', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(['contract', 'token_id', 'onchain_cid', 'reason'])
        w.writerows(failures)
    print(f'regen: {len(plan)} docs written, {len(failures)} failed → {a.out_dir}/plan.csv, regen_failures.csv')
    print('next: pin-docs.py uploads + pins the docs and emits updates_<contract>.csv for tools/update-tezos-metadata')
if failures:
    sys.exit(1)
