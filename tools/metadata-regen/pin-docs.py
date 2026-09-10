#!/usr/bin/env python3
"""Phase-2 step 3 (V3): upload the regenerated docs to prod-02, pin them, and
emit per-contract updates CSVs for tools/update-token-uri.

Takes v3-doc-regen.py's plan.csv. Per contract: batch-uploads the docs into
an MFS staging dir (`/phase2-v3docs/<contract>/`, resumable — files already
present are skipped), reads each doc's CID from ONE `files/ls`, pins the
staging dir root (recursive — covers every doc; prod-02 is Gateway.NoFetch,
ff-deploy#28), and writes:

  <out-dir>/updates_<contract>.csv   edition,token_id,old_metadata_cid,new_metadata_cid

which is exactly tools/update-token-uri's input (use a per-contract
config.json with "docSuffix": ""). The MFS staging dir is KEPT (its root pin
is the pin) — record its root CID in the run notes; unpin only via the
superseded-metadata backlog process.

Run with the tunnel open (make ipfs-port-forward ENV=prod HOST=prod-02):
  python3 tools/metadata-regen/pin-docs.py \
      --plan ops/cdn-retirement-phase2/step3/v3-docs/plan.csv \
      --out-dir ops/cdn-retirement-phase2/step3
"""
import argparse, csv, os, sys, urllib.parse
from collections import defaultdict
import requests

ap = argparse.ArgumentParser()
ap.add_argument('--plan', required=True)
ap.add_argument('--out-dir', required=True)
ap.add_argument('--api', default='http://127.0.0.1:5001')
ap.add_argument('--batch-files', type=int, default=200)
a = ap.parse_args()
API = a.api.rstrip('/') + '/api/v0'
S = requests.Session()

def api(path, **params):
    r = S.post(f'{API}/{path}', params=params, timeout=600)
    r.raise_for_status()
    return r

rows = list(csv.DictReader(open(a.plan)))
by_contract = defaultdict(list)
for r in rows:
    by_contract[r['contract']].append(r)
print(f'{len(rows)} docs on {len(by_contract)} contracts')
os.makedirs(a.out_dir, exist_ok=True)

CID_OK = lambda c: c and (c.startswith('Qm') or c.startswith('baf'))
failures = 0
for contract, toks in sorted(by_contract.items()):
    mfs = f'/phase2-v3docs/{contract}'
    api('files/mkdir', arg=mfs, parents='true', **{'cid-version': 0})
    existing = {e['Name'] for e in (api('files/ls', arg=mfs).json().get('Entries') or [])}
    pending = [r for r in toks if os.path.basename(r['doc_file']) not in existing]
    print(f'{contract}: {len(toks)} docs, {len(toks)-len(pending)} already staged, {len(pending)} to upload')
    for i in range(0, len(pending), a.batch_files):
        batch = pending[i:i + a.batch_files]
        parts = [('file', (urllib.parse.quote(os.path.basename(r['doc_file']), safe=''),
                           open(r['doc_file'], 'rb'))) for r in batch]
        r2 = S.post(f'{API}/add',
                    params={'quieter': 'true', 'cid-version': 0, 'pin': 'false',
                            'to-files': mfs + '/'},
                    files=parts, timeout=1800)
        r2.raise_for_status()
        for _n, fh in parts:
            fh[1].close()
        print(f'  uploaded {min(i + a.batch_files, len(pending))}/{len(pending)}')
    # one ls gives every doc's CID
    entries = {e['Name']: e['Hash'] for e in (api('files/ls', arg=mfs, long='true').json().get('Entries') or [])}
    root = api('files/stat', arg=mfs).json()['Hash']
    api('pin/add', arg=root)
    print(f'  staging root {root} pinned ({len(entries)} docs)')
    out = os.path.join(a.out_dir, f'updates_{contract}.csv')
    n_bad = 0
    with open(out, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['edition', 'token_id', 'old_metadata_cid', 'new_metadata_cid'])
        for r in sorted(toks, key=lambda x: int(x['token_id'])):
            cid = entries.get(os.path.basename(r['doc_file']), '')
            if not CID_OK(cid) or not r['edition']:
                n_bad += 1
                print(f'  MISSING cid/edition for …{r["token_id"][-8:]} (cid={cid!r}, ed={r["edition"]!r})')
                continue
            w.writerow([r['edition'], r['token_id'], r['old_metadata_cid'], cid])
    failures += n_bad
    print(f'  wrote {out} ({len(toks)-n_bad} rows)')
    # record the staging root alongside the updates
    with open(os.path.join(a.out_dir, 'staging_roots.csv'), 'a', newline='') as f:
        csv.writer(f).writerow([contract, mfs, root, len(entries)])
if failures:
    sys.exit(f'{failures} docs missing a CID or edition — investigate before preflight')
print('\nnext per contract: tools/update-token-uri with docSuffix "" -> preflight -> run-all')
