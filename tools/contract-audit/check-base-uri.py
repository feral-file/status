#!/usr/bin/env python3
"""Phase-2 Step 0b: verify each population contract's live tokenURI routing.

Reads population_by_contract.csv (from population.py), calls
`tokenURI(sample_token_id)` on chain for each contract, and classifies where
the link layer actually points:

  ff_api      https://feralfile.com/api/…        (expected for V4/V4_2)
  ff_gateway  https://ipfs.feralfile.com/ipfs/…  or ipfs.bitmark.com
                                                 (expected for V3)
  ipfs        ipfs://…                            (FF-free already)
  other       anything else                       (investigate)

History: the plan assumed V4 base URIs point at the feralfile.com API; the
first run (2026-09-02) measured `ipfs` for both V4-family contracts — the
base URI is already an IPFS directory of tokenId-named docs, so the V4 fix
is one setTokenBaseURI (onlyOwner) per contract and the authoritative fix
list comes from that directory (see v4-dir-audit.py). Expectations below
encode the measured reality; owner() is recorded for the V4 contracts.
Exits 1 on any expectation mismatch.

For V3 it also parses the trailing bare CID (no /metadata.json suffix) and
records it, confirming the audit tool's parsing assumption.

Usage (RPC required — public RPCs are DNS-blocked on the office network,
use Infura):
  RPC_URL=https://mainnet.infura.io/v3/<key> python3 tools/contract-audit/check-base-uri.py \
      --contracts ops/cdn-retirement-phase2/step0/population_by_contract.csv \
      --out ops/cdn-retirement-phase2/step0/base_uri_check.csv
"""
import argparse, csv, json, os, re, sys, time, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument('--contracts', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--timeout', type=float, default=20)
a = ap.parse_args()
RPC = os.environ.get('RPC_URL') or sys.exit('RPC_URL env required (Infura; public RPCs are blocked here)')

def token_uri(contract, token_id):
    data = '0xc87b56dd' + hex(int(token_id))[2:].rjust(64, '0')
    payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'eth_call',
               'params': [{'to': contract, 'data': data}, 'latest']}
    for attempt in range(3):
        try:
            req = urllib.request.Request(RPC, json.dumps(payload).encode(),
                                         {'Content-Type': 'application/json'})
            r = json.load(urllib.request.urlopen(req, timeout=a.timeout))
            if 'error' in r:
                raise RuntimeError(r['error'])
            h = r['result'][2:]
            ln = int(h[64:128], 16)
            return bytes.fromhex(h[128:128 + ln * 2]).decode()
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))

CID_RE = re.compile(r'/(Qm[1-9A-HJ-NP-Za-km-z]{44}|baf[a-z0-9]{20,})/?$')
DIR_RE = re.compile(r'^ipfs://(Qm[1-9A-HJ-NP-Za-km-z]{44}|baf[a-z0-9]{20,})/')

def eth_call(contract, data):
    payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'eth_call',
               'params': [{'to': contract, 'data': data}, 'latest']}
    req = urllib.request.Request(RPC, json.dumps(payload).encode(),
                                 {'Content-Type': 'application/json'})
    r = json.load(urllib.request.urlopen(req, timeout=a.timeout))
    if 'error' in r:
        raise RuntimeError(r['error'])
    return r['result']

def owner_of(contract):
    try:
        return '0x' + eth_call(contract, '0x8da5cb5b')[-40:]  # owner()
    except Exception as e:
        return 'ERROR: ' + str(e)[:80]

def classify(uri):
    if uri.startswith('ipfs://'):
        return 'ipfs'
    if 'feralfile.com/api/' in uri or uri.startswith('https://feralfile.com/'):
        return 'ff_api'
    if 'ipfs.feralfile.com/ipfs/' in uri or 'ipfs.bitmark.com/ipfs/' in uri:
        return 'ff_gateway'
    return 'other'

# Measured 2026-09-02: both V4-family contracts' live base URI is already an
# IPFS directory (ipfs://<dirCID>/<tokenId>) — NOT the feralfile.com API the
# plan doc assumed. The expectation now encodes that measured reality; a V4
# contract answering ff_api again would be a regression worth stopping on.
EXPECT = {'V2': 'ff_gateway', 'V3': 'ff_gateway', 'V4': 'ipfs', 'V4_2': 'ipfs'}

rows, mismatches = [], []
with open(a.contracts) as f:
    for r in csv.DictReader(f):
        c, v = r['contract'], r['version']
        try:
            uri = token_uri(c, r['sample_token_id'])
            cls = classify(uri)
            cid = (m.group(1) if (m := CID_RE.search(uri)) else '')
            exp = EXPECT.get(v, '?')
            ok = (cls == exp)
            depends_ff = cls in ('ff_api', 'ff_gateway')
            note = ''
            if v in ('V3', 'V2') and cls == 'ff_gateway' and not cid:
                ok, note = False, 'gateway URI but no trailing CID parsed'
            owner = ''
            if v in ('V4', 'V4_2'):
                # the V4 fix is one setTokenBaseURI (onlyOwner) per contract —
                # record who owns it so the vault-key question is settled here
                owner = owner_of(c)
                dirm = DIR_RE.match(uri)
                cid = dirm.group(1) if dirm else cid
                if not dirm and cls == 'ipfs':
                    ok, note = False, 'ipfs URI but no dir CID parsed'
        except Exception as e:
            uri, cls, cid, exp, ok, depends_ff, note, owner = \
                '', 'ERROR', '', EXPECT.get(v, '?'), False, '', str(e)[:120], ''
        rows.append([c, v, r['series_hint'], r['sample_token_id'], uri, cls, exp,
                     ok, depends_ff, cid, owner, note])
        flag = 'ok' if ok else 'MISMATCH'
        print(f'{c}  {v:5s} -> {cls:10s} (expect {exp}) {flag}'
              + (f'  owner={owner}' if owner else ''))
        print(f'    {uri}')
        if not ok:
            mismatches.append(c)

os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
with open(a.out, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['contract', 'version', 'series_hint', 'sample_token_id', 'token_uri',
                'classification', 'expected', 'matches_expectation', 'depends_on_ff_server',
                'cid', 'owner', 'note'])
    w.writerows(rows)
print(f'\nwrote {a.out}: {len(rows)} contracts, {len(mismatches)} mismatches')
if mismatches:
    print('MISMATCHES — re-check the plan for these before running anything:')
    for c in mismatches:
        print(f'  {c}')
    sys.exit(1)
