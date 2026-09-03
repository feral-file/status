#!/usr/bin/env python3
"""Emit one tools/update-token-uri config per contract from audit.contracts.csv
and pin.sh's updates/<contract>.csv.

  python3 make-configs.py --contracts audit.contracts.csv --sender-account <vault account> [--expect-trustee 0x…]

Writes runs/<contract>/config.json (gitignored). senderAddress = the on-chain
trustee read by audit.py; --expect-trustee refuses any contract whose trustee
differs (the vault holds one trustee key — a different trustee cannot be signed).
Each config points progress/txreq files into its own runs/<contract>/ directory
so contracts never share a progress.json.
"""
import argparse, csv, json, os, sys
ap = argparse.ArgumentParser()
ap.add_argument('--contracts', default='audit.contracts.csv'); ap.add_argument('--sender-account', required=True)
ap.add_argument('--expect-trustee'); ap.add_argument('--gateway', default='https://ipfs.bitmark.com/ipfs/')
ap.add_argument('--sender-address', help='explicit senderAddress when the audit could not read trustee() (e.g. V3 contracts without the getter); the per-token dry-run in preflight is the real authorization check')
ap.add_argument('--doc-suffix', default=None, help="write docSuffix into each config; V3 contracts need '' (bare doc CID in tokenURI)")
ap.add_argument('--max-gas-gwei', type=float, default=1.0, help='gas price ceiling written to each config (maxGasPriceGwei); update-token-uri waits until baseFee+tip is at or below it')
a = ap.parse_args()
here = os.path.dirname(os.path.abspath(__file__)); os.chdir(here)
n = 0
for r in csv.DictReader(open(a.contracts)):
    c = r['contract'].lower(); upd = f'updates/{c}.csv'
    if not os.path.exists(upd): print(f'skip {c}: no {upd} (nothing pinned for it)'); continue
    sender = r['trustee'] or a.sender_address
    if not sender: sys.exit(f'{c}: trustee unknown and no --sender-address given')
    if a.expect_trustee and sender.lower() != a.expect_trustee.lower(): sys.exit(f'{c}: sender {sender} ≠ expected {a.expect_trustee}')
    d = f'runs/{c}'; os.makedirs(d, exist_ok=True)
    cfg = {'chainId': 1, 'contract': c, 'senderAddress': sender, 'senderAccount': a.sender_account,
           'metadataGateway': a.gateway, 'updates': os.path.abspath(upd), 'workDir': os.path.abspath(d), 'maxGasPriceGwei': a.max_gas_gwei}
    if a.doc_suffix is not None:
        cfg['docSuffix'] = a.doc_suffix
    json.dump(cfg, open(f'{d}/config.json', 'w'), indent=2); n += 1
    print(f'{d}/config.json  ({sum(1 for _ in open(upd)) - 1} rows)')
print(f'{n} configs. Run each with UPDATE_CONFIG=$PWD/runs/<contract>/config.json from tools/update-token-uri.')
