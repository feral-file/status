#!/usr/bin/env python3
"""Map OpenSea collection slugs (Ryan's 2026-09-04 list, categories 2/3/7 = the non-platform
'special-project' class) to Ethereum contract addresses, from the collection page's embedded
data. Paced 1 page/s; resumable via --out (existing slugs skipped)."""
import csv, json, re, sys, time, urllib.request, os
from collections import Counter
src = 'ops/opensea-metadata-path/opensea_ff_collections_full_2026-09-04.csv'
out = sys.argv[1] if len(sys.argv) > 1 else 'ops/special-project-contracts/slug_contracts.csv'
rows = [r for r in csv.DictReader(open(src)) if r['category'][0] in '237']
done = {}
if os.path.exists(out):
    for r in csv.DictReader(open(out)): done[r['opensea_slug']] = r
OWNER_ADDRS = {'0x1d05cf6c6beb0c869851bfdb9510d4e44e855ad6'}
IGNORE = {'0x0000000000000000000000000000000000000000', '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'}  # zero, WETH
w = csv.DictWriter(open(out, 'a', newline=''), fieldnames=['category', 'opensea_slug', 'contract', 'contract_mentions', 'other_addrs', 'http'], lineterminator='\n')
if not done: w.writeheader()
for r in rows:
    s = r['opensea_slug']
    if s in done: continue
    try:
        html = urllib.request.urlopen(urllib.request.Request(f'https://opensea.io/collection/{s}', headers={'User-Agent': 'Mozilla/5.0'}), timeout=60).read().decode('utf-8', 'replace'); http = 200
    except urllib.error.HTTPError as e: html, http = '', e.code
    except Exception as e: html, http = '', str(e)[:40]
    c = Counter(a.lower() for a in re.findall(r'0x[0-9a-fA-F]{40}', html))
    cands = [(a, n) for a, n in c.most_common() if a not in IGNORE and a not in OWNER_ADDRS]
    top = cands[0][0] if cands else ''
    row = {'category': r['category'], 'opensea_slug': s, 'contract': top, 'contract_mentions': cands[0][1] if cands else 0,
           'other_addrs': ';'.join(f'{a}:{n}' for a, n in cands[1:4]), 'http': http}
    w.writerow(row); print(f"{s:60s} {top or '-':44s} {row['contract_mentions']:>4} {http}", flush=True)
    time.sleep(1)
