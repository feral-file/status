#!/usr/bin/env python3
"""Phase-2 Step 0a: rebuild the population from a fresh census (offline).

Implements ops/cdn-retirement-phase2.md "The plan" step 0: the population is
every ETH token with at least one media row pointing at the CDN hosts
(`cdn.feralfileassets.com` / `imagedelivery.net` — the doc's narrow fix rule;
`aesthetic.computer` and other third-party hosts are recorded separately,
they are a product decision, not a migration). Ten Whistlegraphs
(0x9294c5…) is excluded per the doc: its on-chain metadata is all-ipfs://,
the census sees aesthetic.computer only via the API's
alternativePreviewURI overlay.

Cross-checks against phase 1's goal-2 result (ops/bitmark-cdn-retirement/
result.csv): any population token that phase 1 already fixed is a red flag
(the fresh census should show none) — listed and counted, exit 1 if found.

Usage:
  python3 tools/phase2-step0/population.py \
      --census data/census/token_census_20260901T093949Z.csv \
      --goal2-result ops/bitmark-cdn-retirement/result.csv \
      --out-dir ops/cdn-retirement-phase2/step0

Outputs (all CSV, in --out-dir):
  population_tokens.csv       one row per token in the pipeline population
  population_by_contract.csv  contract totals + version + a sample token id
                              (input to check-base-uri.py)
  cdn_dirs.csv                the distinct CDN directories / files to mirror
                              in step 1 (size these at the origin bucket)
  third_party.csv             media rows on third-party hosts (excluded)
  excluded_tokens.csv         tokens excluded from the pipeline, with reason
Prints the by-exhibition table for comparison against the plan doc.
"""
import argparse, csv, os, re, sys
from collections import defaultdict

CDN_HOSTS = {'cdn.feralfileassets.com', 'imagedelivery.net'}
EXCLUDED_CONTRACTS = {
    # Ten Whistlegraphs: on-chain metadata all-ipfs (phase-1 verified); census
    # sees aesthetic.computer via the API alternativePreviewURI overlay.
    '0x9294c5787f5bc7462e991fe8b6feac75f433ac39': 'ten-whistlegraphs: overlay artifact, product decision',
}
# From ops/cdn-retirement-phase2.md (2026-09-01). A contract in the fresh
# census but not here is flagged UNKNOWN — verify before running anything.
VERSIONS = {
    '0xbe0a4e26a156b2a60cf515e86b3df9756dee1952': ('V4_2', 'crystalline work'),
    '0xe46a41b840176b62983fc71162dc9faeac4d9bcb': ('V3', 'I KNOW'),
    '0x2a86c5466f088caebf94e071a77669bae371cd87': ('V3', 'Peer to Peer'),
    '0xc4f0ee96676d3de800b9725eb628de1c5a0cbea1': ('V3', 'Chain Reaction'),
    '0x6003994adeca13407e8dbee808280cc3ef2ab820': ('V3', 'BOOM TOWN'),
    '0x6e82e4b398ca4137007ba69ddd6ff699334d13b5': ('V3', 'Gray Matter'),
    '0xbb12686c360e9057be3cd031140035a705e19cec': ('V4', 'Truth'),
    '0x8f30722dd16bd63cf2665c383c1aef5e307b0046': ('V3', 'Material Wonderland'),
}
DIR_RE = re.compile(r'^(https://[^/]+/(?:previews|thumbnails)/[0-9a-f-]{36}/\d+/)')

ap = argparse.ArgumentParser()
ap.add_argument('--census', required=True)
ap.add_argument('--goal2-result', required=True)
ap.add_argument('--out-dir', required=True)
a = ap.parse_args()

goal2_fixed = set()
with open(a.goal2_result) as f:
    for r in csv.DictReader(f):
        goal2_fixed.add((r['contract'].lower(), r['token_id']))

tokens = defaultdict(lambda: {'rows': [], 'exh': None})   # (contract, token_id) -> media rows
third_party, excluded = [], []
with open(a.census) as f:
    for r in csv.DictReader(f):
        if r['chain'] != 'eth' or r['resource'] == 'metadata':
            continue
        host = r['host_or_gateway']
        if host in CDN_HOSTS:
            c = r['contract'].lower()
            if c in EXCLUDED_CONTRACTS:
                excluded.append({**r, 'reason': EXCLUDED_CONTRACTS[c]})
                continue
            t = tokens[(c, r['token_id'])]
            t['rows'].append(r)
            t['exh'] = r['exhibition']
        elif r['hosting'] in ('cdn', 'other') and host:   # third-party (aesthetic.computer, …)
            reason = EXCLUDED_CONTRACTS.get(r['contract'].lower(), 'third-party host: product decision')
            third_party.append({**r, 'reason': reason})

# cross-check: nothing phase 1 fixed may reappear
regressions = sorted(k for k in tokens if k in goal2_fixed)

os.makedirs(a.out_dir, exist_ok=True)
def write(name, header, rows):
    with open(os.path.join(a.out_dir, name), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)
    print(f'  wrote {name}: {len(rows)} rows')

write('population_tokens.csv',
      ['contract', 'token_id', 'exhibition', 'n_cdn_rows', 'resources', 'urls'],
      [[c, t, d['exh'], len(d['rows']),
        ';'.join(sorted({r['resource'] for r in d['rows']})),
        ';'.join(sorted({r['url'] for r in d['rows']}))]
       for (c, t), d in sorted(tokens.items())])

by_contract = defaultdict(lambda: {'tokens': set(), 'rows': 0, 'exh': set(), 'sample': None})
for (c, t), d in sorted(tokens.items()):
    b = by_contract[c]
    b['tokens'].add(t); b['rows'] += len(d['rows']); b['exh'].add(d['exh'])
    if b['sample'] is None: b['sample'] = t
write('population_by_contract.csv',
      ['contract', 'version', 'series_hint', 'exhibitions', 'n_tokens', 'n_cdn_rows', 'sample_token_id'],
      [[c, *VERSIONS.get(c, ('UNKNOWN', 'VERIFY — not in plan doc')),
        ';'.join(sorted(b['exh'])), len(b['tokens']), b['rows'], b['sample']]
       for c, b in sorted(by_contract.items(), key=lambda x: -len(x[1]['tokens']))])

dirs = defaultdict(lambda: {'rows': 0, 'tokens': set(), 'urls': set(), 'exh': set()})
for (c, t), d in tokens.items():
    for r in d['rows']:
        m = DIR_RE.match(r['url'])
        unit = m.group(1) if m else r['url'].split('?')[0]  # bare file (no dir shape) = its own unit
        u = dirs[unit]
        u['rows'] += 1; u['tokens'].add((c, t)); u['urls'].add(r['url']); u['exh'].add(r['exhibition'])
write('cdn_dirs.csv',
      ['dir_or_file', 'n_rows', 'n_tokens', 'n_distinct_urls', 'exhibitions', 'sample_url'],
      [[k, v['rows'], len(v['tokens']), len(v['urls']), ';'.join(sorted(v['exh'])), sorted(v['urls'])[0]]
       for k, v in sorted(dirs.items(), key=lambda x: -len(x[1]['tokens']))])

write('third_party.csv',
      ['contract', 'token_id', 'exhibition', 'resource', 'url', 'host', 'reason'],
      [[r['contract'], r['token_id'], r['exhibition'], r['resource'], r['url'],
        r['host_or_gateway'], r['reason']] for r in third_party])
write('excluded_tokens.csv',
      ['contract', 'token_id', 'exhibition', 'resource', 'url', 'reason'],
      [[r['contract'], r['token_id'], r['exhibition'], r['resource'], r['url'], r['reason']]
       for r in excluded])

# --- summary -----------------------------------------------------------------
by_exh = defaultdict(set)
for (c, t), d in tokens.items():
    by_exh[(d['exh'], c)].add(t)
print(f'\nPopulation: {len(tokens)} tokens, '
      f'{sum(len(d["rows"]) for d in tokens.values())} CDN media rows, '
      f'{len(dirs)} pin units (dirs/files)\nBy exhibition:')
for (e, c), ts in sorted(by_exh.items(), key=lambda x: -len(x[1])):
    v = VERSIONS.get(c, ('UNKNOWN',))[0]
    print(f'  {len(ts):6d}  {e[:8]}  {c}  {v}')
print(f'Excluded (overlay artifact): {len({(r["contract"], r["token_id"]) for r in excluded})} tokens; '
      f'third-party rows recorded: {len(third_party)}')
if regressions:
    print(f'\nERROR: {len(regressions)} tokens fixed by goal 2 are back in the CDN class:')
    for c, t in regressions[:20]: print(f'  {c} {t}')
    sys.exit(1)
print('goal-2 cross-check: clean (no fixed token reappears)')
