#!/usr/bin/env python3
"""Re-probe tokens that one census has and another lacks, with the census's
own scanner, and emit rows in the same CSV shape so the two files align.

  python3 rescan.py --monitor ~/agentic-workflows/token-health-monitor \
                    --reference data/census/token_census_A.csv \
                    --target    data/census/token_census_B.csv \
                    [--append]  [--config token_health_config.yaml]

Tokens present in --reference but absent from --target are scanned with
census._TokenScanner (identical probes: metadata endpoint, per-CID checks on
every census.ipfs_probe_gateways, CDN/other health). Output goes to
<target>.rescan.csv, or is appended to --target with --append. The daemon's
universe walk drops tokens held by Feral File contracts (vault / bridge); this
is how such tokens are kept measured rather than silently missing.

Needs a venv with requests + PyYAML (the monitor's pinned deps). Uses the
monitor's example config unless --config is given; the config's state paths
are irrelevant here (no cache, no dedup, no checkpoint is touched).
"""
import argparse, csv, os, sys, tempfile, collections
ap = argparse.ArgumentParser()
ap.add_argument('--monitor', required=True, help='path to agentic-workflows/token-health-monitor')
ap.add_argument('--reference', required=True); ap.add_argument('--target', required=True)
ap.add_argument('--config'); ap.add_argument('--append', action='store_true')
a = ap.parse_args()
sys.path.insert(0, os.path.abspath(a.monitor))
import requests, census, config as config_module, discovery
from config import RunMode
cfg_path = a.config or os.path.join(a.monitor, 'token_health_config.example.yaml')
cfg = config_module.load(cfg_path, overrides={'mode': RunMode.CENSUS, 'dry_run': True, 'verbose': False, 'sync_exhibition_id': None})
key = lambda r: (r['chain'], r['contract'], r['token_id'])
ref = list(csv.DictReader(open(a.reference))); tgt = list(csv.DictReader(open(a.target)))
have = {key(r) for r in tgt}
todo = {key(r): discovery.TokenRef(chain=r['chain'], contract=r['contract'], token_id=r['token_id'], exhibition_id=r['exhibition'])
        for r in ref if r['resource'] == 'metadata' and key(r) not in have}
header = list(tgt[0].keys())
scanner = census._TokenScanner(cfg, requests.Session())
if scanner.header != header: sys.exit(f'header mismatch: scanner {scanner.header} vs target {header} — gateway list differs')
print(f'{len(todo)} tokens to rescan', file=sys.stderr)
rows = []
for t in todo.values():
    out = scanner.scan_token(t); rows += out
    print(f'  …{t.token_id[-8:]} ' + ' | '.join(f"{r['resource']}:{(r['ipfs_io_ok'] or r['http_status'])[:14]}" for r in out), file=sys.stderr)
out_path = a.target if a.append else a.target + '.rescan.csv'
with open(out_path, 'a' if a.append else 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=header)
    if not a.append: w.writeheader()
    w.writerows(rows)
print(f'{len(rows)} rows {"appended to" if a.append else "written to"} {out_path}', file=sys.stderr)
print('gateway results:', collections.Counter((r['ipfs_io_ok'], r['ipfs_feralfile_com_ok'], r['dweb_link_ok']) for r in rows if r['cid']).most_common(), file=sys.stderr)
