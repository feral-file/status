#!/usr/bin/env python3
"""Scan OpenSea delist status for tokens we repointed (feral-file#3435).

Trigger (2026-09-04): Infinite Entropy tokens showing "delisted for a
suspected violation of our Terms of Service" after the goal-2 repointing +
OpenSea refresh. This scans EVERY token we fixed, plus a control sample of
UNTOUCHED tokens on the same contracts, so correlation with our changes is
measurable rather than assumed.

Detection: OpenSea's public persisted GraphQL (no auth):
  itemByIdentifier __typename == "DelistedItem"  -> delisted
                              == "Item"          -> normal
Paced (default 2.5 rps) with backoff on 429; resumable via --state.

  python3 tools/opensea-delist-scan.py \
      --state ops/cdn-retirement-phase2/opensea_delist_state.jsonl \
      --out   ops/cdn-retirement-phase2/opensea_delist_report.csv
"""
import argparse, csv, json, os, sys, time, urllib.parse, urllib.request

GQL = 'https://gql.opensea.io/graphql'
EXT = json.dumps({"persistedQuery": {"sha256Hash": "4ff18ba65ce77ce1d817fb5472eb0653aa8f95d3c712ce1db8de5ba7f7f1e40a", "version": 1}})
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36'

ap = argparse.ArgumentParser()
ap.add_argument('--state', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--rps', type=float, default=2.5)
ap.add_argument('--controls-per-contract', type=int, default=15)
a = ap.parse_args()

# --- population --------------------------------------------------------------
tokens = {}   # (contract, token_id) -> group label
def add(contract, tid, group):
    tokens.setdefault((contract.lower(), tid), group)

# goal-2: every repointed V2 token
for r in csv.DictReader(open('ops/bitmark-cdn-retirement/result.csv')):
    tid = r['token_id']
    if not tid.isdigit():
        tid = str(int(tid, 16))
    add(r['contract'], tid, 'fixed:goal2')
# HLS fix: Rewilded Topography (ETH)
try:
    for r in csv.DictReader(open('ops/3435-hls-fix/rewilded-metadata-fix/result.csv')):
        add('0xaDB387798599f5777CD0531c2ECb36007C1D1a51', r['token_id'], 'fixed:hls')
except FileNotFoundError:
    print('note: rewilded result.csv not found, skipping', file=sys.stderr)
# controls: untouched (needs_fix=0) tokens on the same goal-2 contracts
fixed_contracts = {c for (c, _t), g in tokens.items() if g == 'fixed:goal2'}
per = {}
for r in csv.DictReader(open('ops/bitmark-cdn-retirement/audit_2026-08-28.csv')):
    c = r['contract'].lower()
    if c in fixed_contracts and r.get('needs_fix') == '0' and not r.get('error'):
        if per.get(c, 0) < a.controls_per_contract and (c, r['token_id']) not in tokens:
            add(c, r['token_id'], 'control:untouched')
            per[c] = per.get(c, 0) + 1
from collections import Counter
print(f'{len(tokens)} tokens to scan', dict(Counter(tokens.values())), file=sys.stderr)

# --- resume ------------------------------------------------------------------
done = {}
if os.path.exists(a.state):
    for line in open(a.state):
        rec = json.loads(line)
        done[(rec['contract'], rec['token_id'])] = rec
pend = [k for k in tokens if k not in done]
print(f'{len(done)} in state; {len(pend)} to query', file=sys.stderr)

sf = open(a.state, 'a')
delay = 1.0 / a.rps
n = 0
for (c, t) in pend:
    status = None
    for attempt in range(5):
        try:
            v = json.dumps({"identifier": {"chain": "ethereum", "contractAddress": c, "tokenId": t}})
            q = urllib.parse.urlencode({'app_id': 'os2-web', 'operationName': 'ItemAttributesQuery',
                                        'variables': v, 'extensions': EXT})
            req = urllib.request.Request(f'{GQL}?{q}', headers={'User-Agent': UA, 'Accept': 'application/json'})
            d = json.load(urllib.request.urlopen(req, timeout=30))
            item = (d.get('data') or {}).get('itemByIdentifier')
            status = (item or {}).get('__typename') or 'NULL'
            break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(20 * (attempt + 1)); continue
            status = f'HTTP{e.code}'; break
        except Exception as e:
            if attempt == 4:
                status = 'ERR:' + str(e)[:60]
            time.sleep(5)
    sf.write(json.dumps({'contract': c, 'token_id': t, 'group': tokens[(c, t)], 'status': status}) + '\n')
    sf.flush()
    done[(c, t)] = {'status': status}
    n += 1
    if status == 'DelistedItem':
        print(f'DELISTED {c[:10]} …{t[-10:]} [{tokens[(c, t)]}]', flush=True)
    if n % 200 == 0:
        print(f'  {n}/{len(pend)}', file=sys.stderr, flush=True)
    time.sleep(delay)
sf.close()

# --- report ------------------------------------------------------------------
rows = [json.loads(l) for l in open(a.state)]
latest = {}
for r in rows:
    latest[(r['contract'], r['token_id'])] = r
rows = [r for k, r in latest.items() if k in tokens]
stat = Counter((r['group'], r['status']) for r in rows)
by_contract = Counter((r['contract'], r['status']) for r in rows if r['status'] == 'DelistedItem')
with open(a.out, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['contract', 'token_id', 'group', 'status'])
    for r in sorted(rows, key=lambda x: (x['status'] != 'DelistedItem', x['contract'], x['token_id'])):
        w.writerow([r['contract'], r['token_id'], r['group'], r['status']])
print('\nsummary (group, status):')
for k, v in sorted(stat.items()):
    print(f'  {v:6d}  {k}')
print('\ndelisted by contract:')
for (c, _s), v in sorted(by_contract.items(), key=lambda x: -x[1]):
    print(f'  {v:6d}  {c}')
print(f'report: {a.out}')
