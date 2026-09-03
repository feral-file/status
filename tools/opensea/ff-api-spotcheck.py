#!/usr/bin/env python3
"""Spot-check: for every series the OpenSea scan marked non-Centralized
(Decentralized / Delisted / NotIndexed), does the Feral File API actually
serve token metadata at the URL OpenSea would switch to?

  GET https://feralfile.com/api/contracts/<contract>/tokens/<tokenID>

For each such series, N tokens spread across the edition range are fetched and
checked for: HTTP 200, valid JSON, `collection_name`, `collection_uuid`,
`name`, and at least one of `image` / `animation_url`; latency is recorded.
A series PASSES when every sampled token passes. Input is the scan state
written by tools/opensea/collection-metadata-scan.py.

  python3 tools/opensea/ff-api-spotcheck.py \
      --state ops/opensea-metadata-path/scan_state.jsonl \
      --out   ops/opensea-metadata-path/ff_api_spotcheck.csv
"""
import argparse, csv, json, sys, time, urllib.error, urllib.parse, urllib.request
from collections import Counter

FF = 'https://feralfile.com/api'
UA = 'Mozilla/5.0 (compatible; ff-api-spotcheck/1.0)'

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('--state', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--per-series', type=int, default=3)
ap.add_argument('--verdicts', default='Decentralized,Delisted,NotIndexed')
ap.add_argument('--rps', type=float, default=4.0)
a = ap.parse_args()


def get(url, timeout=60):
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read(), time.time() - t0
    except Exception as e:
        return None, str(e).encode(), time.time() - t0


def tokens(series_id, n):
    code, body, _ = get(f'{FF}/artworks?' + urllib.parse.urlencode({'seriesID': series_id, 'limit': max(n * 4, 20)}))
    if code != 200:
        return []
    toks = [(w['contractAddress'], w['tokenID']) for w in json.loads(body)['result']
            if w.get('chain') == 'ethereum' and w.get('contractAddress') and w.get('tokenID')
            and w.get('blockchainStatus') == 'settled']
    if len(toks) > n:
        step = len(toks) // n
        toks = [toks[i * step] for i in range(n)]
    return toks


def check(contract, token):
    code, body, dt = get(f'{FF}/contracts/{contract}/tokens/{token}')
    r = {'http': code, 'latency_s': round(dt, 2)}
    if code != 200:
        r['problem'] = f'HTTP {code}: {body[:100].decode("utf-8", "replace")}'
        return r
    try:
        d = json.loads(body)
    except Exception:
        r['problem'] = 'not JSON'
        return r
    r['collection_name'] = d.get('collection_name')
    r['collection_uuid'] = d.get('collection_uuid')
    r['name'] = d.get('name')
    r['image'] = d.get('image')
    r['animation_url'] = d.get('animation_url')
    missing = [k for k in ('collection_name', 'collection_uuid', 'name') if not d.get(k)]
    if not (d.get('image') or d.get('animation_url')):
        missing.append('image/animation_url')
    r['problem'] = ('missing ' + ','.join(missing)) if missing else ''
    return r


want = set(a.verdicts.split(','))
series = [json.loads(l) for l in open(a.state)]
series = [s for s in series if s['verdict'] in want]
print(f'{len(series)} series to spot-check ({a.per_series} tokens each)', file=sys.stderr)

rows = []
for i, s in enumerate(series, 1):
    toks = tokens(s['series_id'], a.per_series)
    if not toks:
        rows.append({'verdict': s['verdict'], 'series_id': s['series_id'], 'collection_name_expected': s['collection_name'],
                     'problem': 'no settled eth token listed'})
        continue
    for (c, t) in toks:
        r = check(c, t)
        r.update(verdict=s['verdict'], series_id=s['series_id'], exhibition=s.get('exhibition_title'),
                 collection_name_expected=s['collection_name'], collection_uuid_expected=s['collection_uuid'],
                 contract=c, token_id=t)
        if not r['problem']:
            if r['collection_name'] != s['collection_name'] or r['collection_uuid'] != s['collection_uuid']:
                r['problem'] = 'collection fields differ from scan derivation'
        rows.append(r)
        time.sleep(1.0 / a.rps)
    bad = [r for r in rows if r['series_id'] == s['series_id'] and r['problem']]
    print(f'[{i}/{len(series)}] {"FAIL" if bad else "ok  "} {s["collection_name"][:60]!r}'
          + (f'  -> {bad[0]["problem"]}' if bad else ''), flush=True)

cols = ['verdict', 'exhibition', 'collection_name_expected', 'collection_uuid_expected', 'series_id', 'contract',
        'token_id', 'http', 'latency_s', 'problem', 'collection_name', 'collection_uuid', 'name', 'image', 'animation_url']
with open(a.out, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
    w.writeheader()
    for r in sorted(rows, key=lambda r: (not r.get('problem'), r.get('exhibition') or '', r.get('series_id'))):
        w.writerow({k: ('' if r.get(k) is None else r.get(k)) for k in cols})

per_series = {}
for r in rows:
    per_series.setdefault(r['series_id'], []).append(bool(r.get('problem')))
ok = sum(1 for v in per_series.values() if not any(v))
lat = sorted(r['latency_s'] for r in rows if r.get('latency_s') is not None)
print(f'\ntokens checked: {len(rows)}; problems: {sum(1 for r in rows if r.get("problem"))}')
print(f'series passing (all sampled tokens ok): {ok}/{len(per_series)}')
if lat:
    print(f'latency s: median {lat[len(lat)//2]}, p90 {lat[int(len(lat)*0.9)]}, max {lat[-1]}')
print('problems by kind:', dict(Counter(r["problem"].split(":")[0] for r in rows if r.get("problem"))))
print(f'report: {a.out}')
