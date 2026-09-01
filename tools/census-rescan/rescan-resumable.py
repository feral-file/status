#!/usr/bin/env python3
"""Paced, resumable variant of rescan.py --retry-failed (mode B).

Re-probes every token in --target that carries a failed gateway probe, but:
  - paces probes (PACE env, seconds between tokens, default 2) so the
    re-probe itself does not trip the public gateways' rate limits — the
    2026-09-01 census's 429s came from probing ~11k newly content-addressed
    files in one run, and an unpaced retry of 699 tokens hit 429 again;
  - persists each token's result to --state (jsonl) as it lands, so an
    interrupted run resumes where it stopped: tokens whose stored result is
    all-ok are skipped, still-failing ones are re-probed (latest wins);
  - merges into --target only when EVERY failed token has a stored result,
    with mode B's rule unchanged: a token's rows are replaced only if all
    its files pass on all gateways; still-failing tokens keep original rows.

  PACE=5 python3 rescan-resumable.py --monitor ~/agentic-workflows/token-health-monitor \
      --target data/census/token_census_X.csv --state /tmp/rescan-results.jsonl

Rerun the same command until it prints DONE with 0 kept failures (or accept
the remainder as genuine gateway gaps). Delete --state between censuses.
"""
import argparse, csv, json, os, sys, time
ap = argparse.ArgumentParser()
ap.add_argument('--monitor', required=True)
ap.add_argument('--target', required=True)
ap.add_argument('--state', required=True)
ap.add_argument('--config')
a = ap.parse_args()
sys.path.insert(0, os.path.abspath(a.monitor))
import requests, census, config as config_module, discovery
from config import RunMode
PACE = float(os.environ.get('PACE', '2'))
cfg_path = a.config or os.path.join(a.monitor, 'token_health_config.example.yaml')
cfg = config_module.load(cfg_path, overrides={'mode': RunMode.CENSUS, 'dry_run': True, 'verbose': False, 'sync_exhibition_id': None})
key = lambda r: (r['chain'], r['contract'], r['token_id'])
tgt = list(csv.DictReader(open(a.target)))
header = list(tgt[0].keys())
gw = [c for c in header if c.endswith('_ok')]
failed = {key(r) for r in tgt if r['cid'] and any(r[c] != 'ok' for c in gw)}
todo = {k: discovery.TokenRef(chain=r['chain'], contract=r['contract'], token_id=r['token_id'], exhibition_id=r['exhibition'])
        for r in tgt if r['resource'] == 'metadata' and (k := key(r)) in failed}
done = {}
if os.path.exists(a.state):
    for line in open(a.state):
        rec = json.loads(line); done[tuple(rec['key'])] = rec
pend = {k: t for k, t in todo.items() if not (k in done and done[k]['all_ok'])}
print(f'{len(todo)} failed tokens; {len(todo) - len(pend)} already ok in state; {len(pend)} to probe', flush=True)
scanner = census._TokenScanner(cfg, requests.Session())
if scanner.header != header: sys.exit(f'header mismatch: {scanner.header} vs {header}')
with open(a.state, 'a') as sf:
    for i, (k, t) in enumerate(pend.items(), 1):
        out = scanner.scan_token(t)
        all_ok = all(r[c] == 'ok' for r in out if r['cid'] for c in gw)
        sf.write(json.dumps({'key': list(k), 'all_ok': all_ok, 'rows': out}) + '\n'); sf.flush()
        if not all_ok:
            why = '; '.join(f"{r['resource']}:{r[c][:36]}" for r in out if r['cid'] for c in gw if r[c] != 'ok')
            print(f'[{i}/{len(pend)}] ...{t.token_id[-8:]} STILL-FAIL {why}', flush=True)
        elif i % 25 == 0:
            print(f'[{i}/{len(pend)}] ok (progress)', flush=True)
        time.sleep(PACE)
done = {}
for line in open(a.state):
    rec = json.loads(line); done[tuple(rec['key'])] = rec
missing = [k for k in todo if k not in done]
if missing: sys.exit(f'{len(missing)} tokens still unprobed - rerun to continue')
replaced = {k: d['rows'] for k, d in done.items() if k in todo and d['all_ok']}
kept = [k for k in todo if not done[k]['all_ok']]
new_rows = [r for r in tgt if key(r) not in replaced]
for out in replaced.values(): new_rows += out
with open(a.target, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=header); w.writeheader(); w.writerows(new_rows)
print(f'MERGED: replaced {len(replaced)} tokens; {len(kept)} still failing kept as-is; {len(new_rows)} rows in {a.target}', flush=True)
for k in kept: print(f'  still-fail: {k[1][:20]} ...{k[2][-10:]}', flush=True)
print('DONE', flush=True)
