#!/usr/bin/env python3
"""CID-level re-probe of a schema-2 census CSV (the `verdict` column).

Collects every distinct CID reference whose rows carry a selected verdict
(default: `unmeasured` -- the probes a gateway rate-limited or a routing
endpoint errored after the census's retry budget), re-runs ONLY the census's
per-CID primitives (own gateway + one public gateway Feral File does not
operate + delegated-routing providers -> verdict) with the census's own
pacing, records each result to --state (jsonl) as it lands, and rewrites the
affected rows of --target in place once every selected reference has a
result. Resumable: rerun the same command after an interruption; references
already measured are skipped (a result that is still `unmeasured` is
re-probed, latest wins). Finishes in minutes, not hours: the work is per
CID, not per token.

  python3 rescan-cids.py --monitor ~/agentic-workflows/token-health-monitor \
      --target data/census/token_census_X.csv --state /tmp/rescan-cids.jsonl \
      [--verdict unmeasured] [--config token_health_config.yaml]

`--verdict` may repeat (e.g. `--verdict unmeasured --verdict unreachable` to
re-check the gaps too). Delete --state between censuses. Schema-1 CSVs are
refused: use rescan.py for those.
"""
import argparse, csv, json, os, stat, sys, tempfile
from collections import Counter

ap = argparse.ArgumentParser()
ap.add_argument('--monitor', required=True, help='path to agentic-workflows/token-health-monitor')
ap.add_argument('--target', required=True)
ap.add_argument('--state', required=True)
ap.add_argument('--config')
ap.add_argument('--verdict', action='append', help='verdict(s) to re-probe (default: unmeasured)')
a = ap.parse_args()
selected = set(a.verdict or ['unmeasured'])

sys.path.insert(0, os.path.abspath(a.monitor))
import requests, census, checks, config as config_module
from config import RunMode

unknown = selected - set(census.VERDICTS)
if unknown:
    sys.exit(f'--verdict must be one of {list(census.VERDICTS)}; got {sorted(unknown)}')
cfg_path = a.config or os.path.join(a.monitor, 'token_health_config.example.yaml')
cfg = config_module.load(cfg_path, overrides={'mode': RunMode.CENSUS, 'dry_run': True, 'verbose': False, 'sync_exhibition_id': None})
if cfg.census.schema != 2:
    sys.exit('config must have census.schema: 2 for a CID-level rescan')

with open(a.target, newline='') as f:
    reader = csv.DictReader(f)
    header = list(reader.fieldnames or [])
    rows = list(reader)
if 'verdict' not in header:
    sys.exit(f'{a.target} is a schema-1 census (no verdict column); use rescan.py --retry-failed')

scanner = census._TokenScanner(cfg, requests.Session())
if scanner.header != header:
    sys.exit(f'header mismatch: scanner {scanner.header} vs target {header} -- own gateway / schema differs')
measure_cols = [scanner.own_col, 'public_fetch', 'providers_total', 'providers_ff', 'providers_nonff', 'provider_ids', 'verdict', 'detail']

# ref -> (cid, [row indexes]); the reference is <cid>[/path], rebuilt from the
# original URL the same way the census classified it.
todo = {}
for i, r in enumerate(rows):
    if not r['cid'] or r['verdict'] not in selected:
        continue
    rc = checks.classify_resource(r['url'], cdn_hosts=cfg.census.cdn_hosts)
    if not rc.ipfs_ref:
        print(f'row {i}: cid set but url {r["url"]!r} has no ipfs reference; skipped', file=sys.stderr)
        continue
    todo.setdefault(rc.ipfs_ref, (rc.cid, []))[1].append(i)

# State is bound to ONE census file: the first line names the target, and a
# state file left over from a previous census refuses to merge into a new one.
state_tag = {'target': os.path.basename(a.target)}
done = {}
if os.path.exists(a.state) and os.path.getsize(a.state):
    with open(a.state) as sf:
        first = json.loads(sf.readline())
        if first.get('target') != state_tag['target']:
            sys.exit(f'{a.state} belongs to {first.get("target")!r}, not {state_tag["target"]!r}; delete it or pass a fresh --state')
        for line in sf:
            rec = json.loads(line)
            done[rec['ref']] = rec['values']
else:
    with open(a.state, 'w') as sf:
        sf.write(json.dumps(state_tag) + '\n')
pending = {ref: v for ref, v in todo.items() if not (ref in done and done[ref].get('verdict') not in selected)}
print(f'{len(todo)} references ({sum(len(v[1]) for v in todo.values())} rows) with verdict in {sorted(selected)}; '
      f'{len(todo) - len(pending)} already measured in state; {len(pending)} to probe', flush=True)

with open(a.state, 'a') as sf:
    for k, (ref, (cid, idxs)) in enumerate(pending.items(), 1):
        values = scanner.measure_ref(ref, cid)
        sf.write(json.dumps({'ref': ref, 'cid': cid, 'values': values}) + '\n'); sf.flush()
        v = values.get('verdict', '')
        note = '' if v not in selected else '  (still ' + v + ': ' + values.get('public_fetch', '')[:60] + ' ' + values.get('detail', '')[:60] + ')'
        if v in selected or k % 25 == 0 or k == len(pending):
            print(f'[{k}/{len(pending)}] {cid[:16]}... -> {v}{note}', flush=True)

done = {}
with open(a.state) as sf:
    sf.readline()  # target tag
    for line in sf:
        rec = json.loads(line)
        done[rec['ref']] = rec['values']
missing = [ref for ref in todo if ref not in done]
if missing:
    sys.exit(f'{len(missing)} references still unprobed -- rerun to continue')

before = Counter(rows[i]['verdict'] for v in todo.values() for i in v[1])
changed = 0
for ref, (cid, idxs) in todo.items():
    values = done[ref]
    for i in idxs:
        for col in measure_cols:
            if col in values:
                rows[i][col] = values[col]
        changed += 1
after = Counter(rows[i]['verdict'] for v in todo.values() for i in v[1])

fd, tmp = tempfile.mkstemp(prefix=os.path.basename(a.target) + '.', suffix='.tmp', dir=os.path.dirname(os.path.abspath(a.target)))
with os.fdopen(fd, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=header); w.writeheader(); w.writerows(rows)
    f.flush(); os.fsync(f.fileno())
os.chmod(tmp, stat.S_IMODE(os.stat(a.target).st_mode))  # mkstemp is 0600; keep the census file's mode
os.replace(tmp, a.target)
print(f'REWROTE {changed} rows in {a.target}', flush=True)
print(f'  before: {dict(before)}', flush=True)
print(f'  after:  {dict(after)}', flush=True)
still = [ref for ref, v in done.items() if ref in todo and v.get('verdict') in selected]
if still:
    print(f'{len(still)} references still {sorted(selected)} -- rerun later (a new run re-probes them)', flush=True)
print('DONE', flush=True)
