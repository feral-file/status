#!/usr/bin/env python3
"""Per-series scan: which Feral File collections does OpenSea read through the
FF API (Centralized) vs straight from tokenURI (Decentralized)?

Context: ops/opensea-metadata-path-incident.md (feral-file#3435). OpenSea groups
FF tokens into SERIES-level collections using `collection_name` /
`collection_uuid`, which exist ONLY in the FF API response
(GET https://feralfile.com/api/contracts/<contract>/tokens/<tokenID>,
feral-file-server/api/swap.go getEthTokenMetadata). Tokens whose metadata
OpenSea reads directly from tokenURI (ipfs.bitmark.com / ipfs) carry no such
fields and can be re-bucketed into auto-generated duplicate collections.

How the FF API generates the two fields (api/swap.go, published contracts):
  collection_name = series.metadata.collectionName   if set and non-empty
                  = "<series.title> by <artist.alias>" otherwise
                    (alias = alumniAccount.alias with "<A2P>", "_tez",
                     "_custody" stripped — schema.AlumniAccount.PrettyAlias)
  collection_uuid = series.metadata.collectionUUID   if set and non-empty
                  = series.id                        otherwise
  (For contracts NOT registered as an FF exhibition contract the API instead
   derives collection_uuid = uuid5(ad1eb04a-a53a-4ca2-8133-e727a2c03971,
   collection_name) from a collection_name already present in the IPFS doc.)

What the scan does, per series (FF public API, no auth):
  1. list every series (/api/series), its artist and exhibition/contracts;
  2. derive collection_name / collection_uuid with the rule above and confirm
     them against the live FF API response for one token;
  3. pick one settled Ethereum token of the series and fetch its OpenSea item
     page (https://opensea.io/item/ethereum/<contract>/<tokenID>, no auth).
     The server-rendered page embeds the item record OpenSea uses:
       "tokenUri":              the metadata URL OpenSea reads
       "metadataStorageLabel":  OpenSea's own CENTRALIZED / DECENTRALIZED label
       collection slug / name / isVerified / owner
     Delisted tokens embed nothing (DelistedItem) -> the next token is tried.
  4. verdict:
       Centralized    tokenUri is https://feralfile.com/api/contracts/...
       Decentralized  tokenUri is anything else (ipfs.bitmark.com, ipfs://, ...)
       Delisted       every sampled token is DelistedItem
       NotIndexed     OpenSea has no item for any sampled token
       NoEthToken     series has no settled Ethereum token (Tezos / unminted)

Paced (default 1 OpenSea page/s), resumable via --state (JSONL, one line per
series). Re-run with --refresh to re-query everything.

  python3 tools/opensea/collection-metadata-scan.py \
      --state ops/opensea-metadata-path/scan_state.jsonl \
      --out   ops/opensea-metadata-path/collections_report.csv \
      --md    ops/opensea-metadata-path/decentralized_collections.md
"""
import argparse, csv, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from collections import Counter

FF = 'https://feralfile.com/api'
OS_ITEM = 'https://opensea.io/item/ethereum/{contract}/{token}'
FF_API_PREFIX = 'https://feralfile.com/api/contracts/'
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/128.0 Safari/537.36')

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('--state', required=True, help='resumable JSONL state (one record per series)')
ap.add_argument('--out', required=True, help='CSV report, every series')
ap.add_argument('--md', help='markdown handoff listing only the non-Centralized series')
ap.add_argument('--handoff-csv', help='compact CSV for OpenSea: non-Centralized series, one row each, minimal columns')
ap.add_argument('--exclude-exhibition', action='append', default=[], help='exhibition title to leave out of the handoff (test/internal)')
ap.add_argument('--rps', type=float, default=1.0, help='OpenSea page fetches per second')
ap.add_argument('--samples', type=int, default=3, help='max tokens to try per series (delisted/unindexed fallback)')
ap.add_argument('--series', action='append', help='only scan these series IDs (repeatable)')
ap.add_argument('--refresh', action='store_true', help='ignore existing state, re-query everything')
ap.add_argument('--skip-ff-verify', action='store_true', help='do not confirm the derived fields against the live FF API')
a = ap.parse_args()


# --- http helpers ------------------------------------------------------------
def get(url, retries=4, timeout=40, accept='application/json'):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': accept})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504):
                time.sleep(15 * (attempt + 1)); last = e; continue
            return e.code, e.read()
        except Exception as e:  # timeouts, resets
            last = e
            time.sleep(5 * (attempt + 1))
    return None, str(last)


def ff_json(path, **params):
    q = ('?' + urllib.parse.urlencode(params)) if params else ''
    code, body = get(f'{FF}{path}{q}')
    if code != 200:
        raise RuntimeError(f'FF {path} -> {code}: {body[:120] if isinstance(body, bytes) else body}')
    return json.loads(body)


# --- FF side ---------------------------------------------------------------------
def pretty_alias(alias):
    return re.sub(r'<A2P>|_tez|_custody', '', alias or '')


def derive_collection(series):
    """Mirror api/swap.go getEthTokenMetadata (published-contract path)."""
    md = series.get('metadata') or {}
    artist = (series.get('artist') or {})
    alias = (artist.get('alumniAccount') or {}).get('alias') or artist.get('alias') or ''
    cn = md.get('collectionName')
    if cn is None:
        name, name_src = f"{series['title']} by {pretty_alias(alias)}", 'derived:title by artist'
    elif cn == '':
        name, name_src = '', 'none:collectionName explicitly empty'
    else:
        name, name_src = cn, 'explicit:series.metadata.collectionName'
    cu = md.get('collectionUUID')
    if cu is None:
        uuid, uuid_src = series['id'], 'derived:series.id'
    elif cu == '':
        uuid, uuid_src = '', 'none:collectionUUID explicitly empty'
    else:
        uuid, uuid_src = cu, 'explicit:series.metadata.collectionUUID'
    return name, name_src, uuid, uuid_src


def list_all_series():
    out, offset = [], 0
    while True:
        d = ff_json('/series', limit=100, offset=offset, includeArtist='true', sortBy='createdAt', sortOrder='ASC')
        out.extend(d['result'])
        offset += 100
        if offset >= d['paging']['total'] or not d['result']:
            break
    return out


_exh_cache = {}
def exhibition(exh_id):
    if exh_id not in _exh_cache:
        try:
            _exh_cache[exh_id] = ff_json(f'/exhibitions/{exh_id}')['result']
        except Exception as e:
            print(f'  warn: exhibition {exh_id}: {e}', file=sys.stderr)
            _exh_cache[exh_id] = {}
    return _exh_cache[exh_id]


def eth_tokens(series_id, n):
    """Settled Ethereum tokens of the series, newest-index first (API default)."""
    d = ff_json('/artworks', seriesID=series_id, limit=max(n * 4, 20))
    toks = [(w['contractAddress'], w['tokenID']) for w in d['result']
            if w.get('chain') == 'ethereum' and w.get('contractAddress') and w.get('tokenID')
            and w.get('blockchainStatus') == 'settled']
    # spread the samples across the edition range instead of the first N
    if len(toks) > n:
        step = len(toks) // n
        toks = [toks[i * step] for i in range(n)]
    return toks


def ff_api_fields(contract, token):
    code, body = get(f'{FF_API_PREFIX}{contract}/tokens/{token}')
    if code != 200:
        return {'ff_api_http': code}
    try:
        d = json.loads(body)
    except Exception:
        return {'ff_api_http': code, 'ff_api_error': 'not json'}
    return {'ff_api_http': code,
            'ff_api_collection_name': d.get('collection_name'),
            'ff_api_collection_uuid': d.get('collection_uuid')}


# --- OpenSea side --------------------------------------------------------------------
def _field(h, key):
    m = re.search(r'"%s":"((?:[^"\\]|\\.)*)"' % re.escape(key), h)
    return json.loads('"' + m.group(1) + '"') if m else None


def opensea_item(contract, token):
    """Parse the item record embedded in the server-rendered OpenSea item page."""
    code, body = get(OS_ITEM.format(contract=contract, token=token), accept='text/html', timeout=60)
    if code != 200:
        return {'os_http': code}
    h = body.decode('utf-8', 'replace').replace('\\"', '"')
    m = re.search(r'"itemByIdentifier":\{"__typename":"([A-Za-z]+)"', h)
    typename = m.group(1) if m else None
    rec = {'os_http': 200, 'os_typename': typename or 'NULL'}
    if typename != 'Item':
        return rec
    # item-level fields: take the segment after itemByIdentifier so we don't pick up
    # unrelated collections rendered elsewhere on the page
    seg = h[m.start():m.start() + 200000]
    rec['os_token_uri'] = _field(seg, 'tokenUri')
    rec['os_storage_label'] = _field(seg, 'metadataStorageLabel')
    rec['os_original_animation'] = _field(seg, 'originalAnimationUrl')
    rec['os_original_image'] = _field(seg, 'originalImageUrl')
    c = re.search(r'"collection":\{"slug":"((?:[^"\\]|\\.)*)"', seg)
    if c:
        rec['os_collection_slug'] = json.loads('"' + c.group(1) + '"')
        cseg = seg[c.start():c.start() + 20000]
        rec['os_collection_name'] = _field(cseg, 'name')
        rec['os_collection_verified'] = (re.search(r'"isVerified":(true|false)', cseg) or [None, None])[1]
        o = re.search(r'"owner":\{[^}]*"displayName":"((?:[^"\\]|\\.)*)"', cseg)
        rec['os_collection_owner'] = json.loads('"' + o.group(1) + '"') if o else None
    return rec


def verdict(rec):
    uri = rec.get('os_token_uri')
    if uri:
        return 'Centralized' if uri.startswith(FF_API_PREFIX) else 'Decentralized'
    t = rec.get('os_typename')
    if t == 'DelistedItem':
        return 'Delisted'
    return 'NotIndexed'


# --- main ------------------------------------------------------------------------------
done = {}
if os.path.exists(a.state) and not a.refresh:
    for line in open(a.state):
        r = json.loads(line)
        done[r['series_id']] = r

print('listing series …', file=sys.stderr)
all_series = list_all_series()
if a.series:
    all_series = [s for s in all_series if s['id'] in set(a.series)]
pend = [s for s in all_series if s['id'] not in done]
print(f'{len(all_series)} series; {len(done)} in state; {len(pend)} to scan', file=sys.stderr)

sf = open(a.state, 'a')
delay = 1.0 / a.rps
for i, s in enumerate(pend, 1):
    exh = exhibition(s['exhibitionID'])
    name, name_src, uuid, uuid_src = derive_collection(s)
    rec = {
        'series_id': s['id'], 'series_title': s['title'], 'series_slug': s.get('slug'),
        'artist_alias': pretty_alias(((s.get('artist') or {}).get('alumniAccount') or {}).get('alias')),
        'exhibition_id': s['exhibitionID'], 'exhibition_title': exh.get('title'),
        'mint_blockchain': exh.get('mintBlockchain'),
        'contracts': ';'.join(f"{c.get('name')}@{c.get('address')}" for c in (exh.get('contracts') or [])
                              if c.get('blockchainType') == 'ethereum'),
        'collection_name': name, 'collection_name_source': name_src,
        'collection_uuid': uuid, 'collection_uuid_source': uuid_src,
        'scanned_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    try:
        toks = eth_tokens(s['id'], a.samples)
    except Exception as e:
        toks, rec['error'] = [], f'artworks: {e}'
    if not toks:
        rec['verdict'] = 'NoEthToken'
    else:
        rec['sampled_tokens'] = len(toks)
        for (c, t) in toks:
            os_rec = opensea_item(c, t)
            time.sleep(delay)
            rec.update(os_rec, sample_contract=c, sample_token_id=t)
            if os_rec.get('os_typename') == 'Item':
                break
        rec['verdict'] = verdict(rec)
        if not a.skip_ff_verify:
            rec.update(ff_api_fields(rec['sample_contract'], rec['sample_token_id']))
            if rec.get('ff_api_http') == 200:
                rec['ff_api_matches_derivation'] = (rec.get('ff_api_collection_name') == name
                                                    and rec.get('ff_api_collection_uuid') == uuid)
    sf.write(json.dumps(rec, ensure_ascii=False) + '\n'); sf.flush()
    done[s['id']] = rec
    flag = '' if rec['verdict'] == 'Centralized' else '  <--'
    print(f'[{i}/{len(pend)}] {rec["verdict"]:13s} {name[:60]!r}{flag}', flush=True)
sf.close()

# --- report --------------------------------------------------------------------------
rows = [done[s['id']] for s in all_series if s['id'] in done]
cols = ['verdict', 'collection_name', 'collection_uuid', 'collection_name_source', 'collection_uuid_source',
        'os_storage_label', 'os_token_uri', 'os_collection_slug', 'os_collection_name', 'os_collection_verified',
        'os_collection_owner', 'os_typename', 'sample_contract', 'sample_token_id', 'sampled_tokens',
        'ff_api_http', 'ff_api_collection_name', 'ff_api_collection_uuid', 'ff_api_matches_derivation',
        'os_original_animation', 'os_original_image', 'series_id', 'series_title', 'series_slug', 'artist_alias',
        'exhibition_id', 'exhibition_title', 'mint_blockchain', 'contracts', 'scanned_at', 'error']
order = {'Decentralized': 0, 'Delisted': 1, 'NotIndexed': 2, 'Centralized': 3, 'NoEthToken': 4}
rows.sort(key=lambda r: (order.get(r['verdict'], 9), r.get('exhibition_title') or '', r['series_title']))
os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
with open(a.out, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
    w.writeheader()
    for r in rows:
        w.writerow({k: ('' if r.get(k) is None else r.get(k)) for k in cols})

cnt = Counter(r['verdict'] for r in rows)
print('\nsummary:')
for k in sorted(cnt, key=lambda k: order.get(k, 9)):
    print(f'  {cnt[k]:5d}  {k}')
lab = Counter((r['verdict'], r.get('os_storage_label')) for r in rows if r.get('os_storage_label'))
dis = [r for r in rows if r.get('os_storage_label') and
       (r['verdict'] == 'Centralized') != (r['os_storage_label'] == 'CENTRALIZED')]
print(f'OpenSea storage label vs tokenUri verdict disagreements: {len(dis)}')
mism = [r for r in rows if r.get('ff_api_matches_derivation') is False]
print(f'FF API fields differing from the derivation rule: {len(mism)}')
for r in mism[:20]:
    print(f"   {r['series_id']} derived={r['collection_name']!r}/{r['collection_uuid']} "
          f"api={r.get('ff_api_collection_name')!r}/{r.get('ff_api_collection_uuid')}")
print(f'report: {a.out}')

if a.md:
    bad = [r for r in rows if r['verdict'] in ('Decentralized', 'Delisted', 'NotIndexed')]
    with open(a.md, 'w') as f:
        f.write('# Feral File collections whose OpenSea metadata does NOT come through the Feral File API\n\n')
        f.write(f'Generated {time.strftime("%Y-%m-%d")} by `tools/opensea/collection-metadata-scan.py`. '
                f'{len(rows)} series scanned; {cnt.get("Centralized", 0)} Centralized (FF API), '
                f'{cnt.get("Decentralized", 0)} Decentralized (tokenURI direct), '
                f'{cnt.get("Delisted", 0)} Delisted (no data on OpenSea), '
                f'{cnt.get("NotIndexed", 0)} NotIndexed, {cnt.get("NoEthToken", 0)} without Ethereum tokens.\n\n')
        f.write('Expected metadata URL for every token: '
                '`https://feralfile.com/api/contracts/<contract>/tokens/<tokenID>` '
                '(returns `collection_name` + `collection_uuid`, which OpenSea uses for series-level grouping).\n\n')
        f.write('| verdict | exhibition | collection_name | collection_uuid | contract | sample token | OpenSea tokenUri (current) | OpenSea label | current OpenSea collection (slug, verified?) |\n')
        f.write('|---|---|---|---|---|---|---|---|---|\n')
        for r in bad:
            f.write('| {v} | {e} | {n} | `{u}` | `{c}` | `{t}` | {uri} | {lab} | {slug} |\n'.format(
                v=r['verdict'], e=(r.get('exhibition_title') or '').replace('|', '\\|'),
                n=(r.get('collection_name') or '(none: collectionName empty in FF DB)').replace('|', '\\|'),
                u=r.get('collection_uuid') or '',
                c=r.get('sample_contract') or '', t=r.get('sample_token_id') or '',
                uri=(r.get('os_token_uri') or '').replace('|', '\\|'), lab=r.get('os_storage_label') or '',
                slug=(f"{r['os_collection_slug']} ({'verified' if r.get('os_collection_verified') == 'true' else 'UNVERIFIED'}"
                      f"{', owner ' + r['os_collection_owner'] if r.get('os_collection_owner') else ''})")
                     if r.get('os_collection_slug') else ''))
    print(f'handoff: {a.md} ({len(bad)} series)')

if a.handoff_csv:
    skip = set(a.exclude_exhibition)
    bad = [r for r in rows if r['verdict'] in ('Decentralized', 'Delisted', 'NotIndexed')
           and (r.get('exhibition_title') or '') not in skip]
    hc = ['status', 'exhibition', 'collection_name', 'collection_uuid', 'contract', 'current_opensea_collection',
          'sample_token_id', 'current_metadata_url', 'expected_metadata_url']
    with open(a.handoff_csv, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(hc)
        for r in bad:
            c, t = r.get('sample_contract') or '', r.get('sample_token_id') or ''
            w.writerow([
                {'Decentralized': 'reads tokenURI directly', 'Delisted': 'delisted (no data)'}.get(r['verdict'], r['verdict']),
                r.get('exhibition_title') or '', r.get('collection_name') or '', r.get('collection_uuid') or '',
                c, r.get('os_collection_slug') or '', t,
                r.get('os_token_uri') or '', f'{FF_API_PREFIX}{c}/tokens/{t}' if c and t else ''])
    print(f'handoff csv: {a.handoff_csv} ({len(bad)} series, excluded exhibitions: {sorted(skip) or "none"})')
