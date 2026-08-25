#!/usr/bin/env python3
"""Re-probe tokens that one census has and another lacks, with the census's
own scanner, and emit rows in the same CSV shape so the two files align.

  # A. tokens in --reference but missing from --target → scan, write/append
  python3 rescan.py --monitor ~/agentic-workflows/token-health-monitor \
                    --reference data/census/token_census_A.csv \
                    --target    data/census/token_census_B.csv \
                    [--append]  [--config token_health_config.yaml]

  # B. tokens in --target with a failed gateway probe → re-probe once; a token
  #    whose files ALL pass now has its rows replaced in --target
  python3 rescan.py --monitor … --target data/census/token_census_B.csv --retry-failed

Both modes use census._TokenScanner (identical probes: metadata endpoint,
per-CID checks on every census.ipfs_probe_gateways, CDN/other health).

Mode A exists because the daemon's universe walk drops tokens held by Feral
File contracts (vault / bridge); this keeps them measured rather than missing.
Mode B exists because a public gateway can answer one HEAD with a 410 or a
timeout and the next with 200; a single-probe failure is not evidence the
file is unavailable. Mode B only ever replaces a token's rows when every
file passes on every gateway on the retry — a token that fails again keeps
its original rows. The replaced originals are printed so the record of what
was retried survives in the commit message / updates entry.

Needs a venv with requests + PyYAML (the monitor's pinned deps). Uses the
monitor's example config unless --config is given; the config's state paths
are irrelevant here (no cache, no dedup, no checkpoint is touched).
"""
import argparse, csv, os, sys, tempfile, collections
ap = argparse.ArgumentParser()
ap.add_argument('--monitor', required=True, help='path to agentic-workflows/token-health-monitor')
ap.add_argument('--reference'); ap.add_argument('--target', required=True)
ap.add_argument('--config'); ap.add_argument('--append', action='store_true'); ap.add_argument('--retry-failed', action='store_true')
a = ap.parse_args()
sys.path.insert(0, os.path.abspath(a.monitor))
import requests, census, config as config_module, discovery
from config import RunMode
cfg_path = a.config or os.path.join(a.monitor, 'token_health_config.example.yaml')
cfg = config_module.load(cfg_path, overrides={'mode': RunMode.CENSUS, 'dry_run': True, 'verbose': False, 'sync_exhibition_id': None})
key = lambda r: (r['chain'], r['contract'], r['token_id'])
tgt = list(csv.DictReader(open(a.target)))
header = list(tgt[0].keys())
scanner = census._TokenScanner(cfg, requests.Session())
if scanner.header != header: sys.exit(f'header mismatch: scanner {scanner.header} vs target {header} — gateway list differs')
gw_cols = [c for c in header if c.endswith('_ok')]
ref_of = lambda r: discovery.TokenRef(chain=r['chain'], contract=r['contract'], token_id=r['token_id'], exhibition_id=r['exhibition'])
def show(t, out): return f"  …{t.token_id[-8:]} " + ' | '.join(f"{r['resource']}:{(r['ipfs_io_ok'] or r['http_status'])[:14]}" for r in out)
def summary(rows): return collections.Counter(tuple(r[c] for c in gw_cols) for r in rows if r['cid']).most_common()

if a.retry_failed:
    failed = {key(r) for r in tgt if r['cid'] and any(r[c] != 'ok' for c in gw_cols)}
    todo = {k: ref_of(r) for r in tgt if r['resource'] == 'metadata' and (k := key(r)) in failed}
    print(f'{len(todo)} tokens with a failed gateway probe — re-probing once', file=sys.stderr)
    replaced, kept = {}, []
    for k, t in todo.items():
        out = scanner.scan_token(t); print(show(t, out), file=sys.stderr)
        if all(r[c] == 'ok' for r in out if r['cid'] for c in gw_cols): replaced[k] = out
        else: kept.append(k)
    orig = [r for r in tgt if key(r) in replaced]
    new_rows = [r for r in tgt if key(r) not in replaced]
    for out in replaced.values(): new_rows += out
    with open(a.target, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=header); w.writeheader(); w.writerows(new_rows)
    print(f'replaced rows for {len(replaced)} token(s); {len(kept)} still failing kept as-is; {len(new_rows)} rows in {a.target}', file=sys.stderr)
    print('original rows that were replaced:', file=sys.stderr)
    for r in orig:
        if r['cid']: print(f"  {r['exhibition'][:8]} …{r['token_id'][-8:]} {r['resource']} {r['cid']} " + ' '.join(f"{c}={r[c][:40]}" for c in gw_cols if r[c] != 'ok'), file=sys.stderr)
    sys.exit(0)

if not a.reference: sys.exit('--reference is required unless --retry-failed')
ref = list(csv.DictReader(open(a.reference)))
have = {key(r) for r in tgt}
todo = {key(r): ref_of(r) for r in ref if r['resource'] == 'metadata' and key(r) not in have}
print(f'{len(todo)} tokens to rescan', file=sys.stderr)
rows = []
for t in todo.values():
    out = scanner.scan_token(t); rows += out; print(show(t, out), file=sys.stderr)
out_path = a.target if a.append else a.target + '.rescan.csv'
with open(out_path, 'a' if a.append else 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=header)
    if not a.append: w.writeheader()
    w.writerows(rows)
print(f'{len(rows)} rows {"appended to" if a.append else "written to"} {out_path}', file=sys.stderr)
print('gateway results:', summary(rows), file=sys.stderr)
