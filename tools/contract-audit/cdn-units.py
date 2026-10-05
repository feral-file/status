#!/usr/bin/env python3
"""Build the CDN pin-unit list (`cdn_dirs.csv`) from chain audits.

`population.py` derives the units from a census; tokens on hidden exhibitions
are in no census, so this derives the same list from the chain audits instead:
`tools/metadata-regen/audit.py` output (ETH: `animation_url`, `image`) and
`tools/metadata-regen/tezos-doc-regen.py --audit-only` output (Tezos:
`cdn_urls`, `;`-joined). Same unit rule as population.py, plus Tezos'
`gallery-thumbnails/`: a URL under `<kind>/<series uuid>/<version>/` belongs to
that directory unit; anything else is a bare-file unit (query stripped).

  python3 tools/contract-audit/cdn-units.py eth_audit.csv tezos_audit.csv \
      [--known ops/cdn-retirement-phase2/step1/dir_cids.csv] --out cdn_dirs.csv

--known: pin-unit registries of earlier runs; units already mirrored there are
listed on stderr and left out (reuse their rows instead of mirroring twice).
Output has the header `tools/ipfs-mirror` expects (it reads column 1).
"""
import argparse, csv, re, sys
from collections import defaultdict

CDN_HOST = 'cdn.feralfileassets.com'
DIR_RE = re.compile(r'^(https://[^/]+/(?:previews|thumbnails|gallery-thumbnails)/[0-9a-f-]{36}/\d+/)')

ap = argparse.ArgumentParser()
ap.add_argument('audits', nargs='+')
ap.add_argument('--known', nargs='*', default=[])
ap.add_argument('--out', default='cdn_dirs.csv')
a = ap.parse_args()

known = {}
for p in a.known:
    for r in csv.DictReader(open(p)):
        if r.get('cid'):
            known[r['dir_or_file']] = r['cid']

units = defaultdict(lambda: {'rows': 0, 'tokens': set(), 'urls': set(), 'contracts': set()})
other_hosts = defaultdict(int)
for p in a.audits:
    for r in csv.DictReader(open(p)):
        if 'cdn_urls' in r:
            urls = [u for u in r['cdn_urls'].split(';') if u]
        else:
            urls = [r.get(k) for k in ('animation_url', 'image') if r.get(k)]
        for u in urls:
            if not u.startswith('http'):
                continue
            host = u.split('/')[2]
            if host != CDN_HOST:
                other_hosts[host] += 1
                continue
            m = DIR_RE.match(u)
            unit = m.group(1) if m else u.split('?')[0]
            x = units[unit]
            x['rows'] += 1; x['tokens'].add((r['contract'], r['token_id'])); x['urls'].add(u); x['contracts'].add(r['contract'])

rows, reused = [], []
for k, v in sorted(units.items(), key=lambda x: (sorted(x[1]['contracts']), x[0])):
    if k in known:
        reused.append((k, known[k])); continue
    rows.append([k, v['rows'], len(v['tokens']), len(v['urls']), ';'.join(sorted(v['contracts'])), sorted(v['urls'])[0]])
with open(a.out, 'w', newline='') as f:
    w = csv.writer(f, lineterminator='\n')
    w.writerow(['dir_or_file', 'n_rows', 'n_tokens', 'n_distinct_urls', 'contracts', 'sample_url'])
    w.writerows(rows)
print(f'{len(rows)} units to mirror → {a.out} ({sum(1 for r in rows if r[0].endswith("/"))} directories, '
      f'{sum(1 for r in rows if not r[0].endswith("/"))} bare files)', file=sys.stderr)
for k, cid in reused:
    print(f'  already mirrored, left out: {k} = {cid}', file=sys.stderr)
for h, n in sorted(other_hosts.items()):
    print(f'  non-CDN http host, not a unit: {h} ({n} rows)', file=sys.stderr)
