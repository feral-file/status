#!/usr/bin/env python3
"""Pass 2: for each candidate non-platform contract, pull every token from indexer-v2 (GraphQL,
contract-filtered, 255/page) with the raw on-chain doc (metadata.origin_json) and classify
where its media lives. Output: tokens CSV (one row per token) + per-contract summary CSV.

Classes per media key (image / animation_url in the ORIGIN doc — what tokenURI points at):
  ipfs        ipfs:// or an IPFS gateway URL (any host, path /ipfs/<cid>)
  ff-cdn      cdn.feralfileassets.com / imagedelivery.net (Feral File-controlled, retiring)
  ff-other    any other feralfile.com / bitmark.com host (incl. ipfs.bitmark.com — still gateway = ipfs)
  third-party any other http(s) host
  none        key absent/empty
Usage: audit-contracts.py candidate_contracts.csv tokens_out.csv summary_out.csv"""
import csv, json, sys, time, urllib.request, urllib.parse
from collections import Counter, defaultdict
GQL = 'https://indexer-v2.feralfile.com/graphql'
# NB: the indexer answers 422/internal error when origin_json is combined with display{}/release_id
# or with GraphQL variables — keep this exact inline shape (measured 2026-09-08).
def gql(c, o):
    Q = '{ tokens(contract_addresses:"%s", limit:100, offset:%d, include_unviewable:true, include_moderated:true) { items { id token_number burned viewable metadata { image_url animation_url enrichment_level origin_json } } } }' % (c, o)
    body = json.dumps({'query': Q}).encode()
    for i in range(5):
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(GQL, body, {'content-type': 'application/json'}), timeout=180))
            if 'errors' in d: raise RuntimeError(d['errors'][0].get('message'))
            return d['data']['tokens']['items']
        except Exception as e:
            if i == 4: raise
            time.sleep(3 * (i + 1))
def cls(v):
    if not v: return 'none'
    v = str(v)
    if v.startswith('ipfs://') or '/ipfs/' in v: return 'ipfs'
    h = urllib.parse.urlparse(v).netloc.lower()
    if h in ('cdn.feralfileassets.com', 'imagedelivery.net') or h.endswith('.feralfileassets.com'): return 'ff-cdn'
    if h.endswith('feralfile.com') or h.endswith('bitmark.com'): return 'ff-other'
    if v.startswith('data:'): return 'inline'
    return 'third-party' if h else 'relative'
cands = list(csv.DictReader(open(sys.argv[1])))
tw = csv.writer(open(sys.argv[2], 'w', newline=''), lineterminator='\n')
tw.writerow(['contract', 'opensea_slug', 'token_number', 'burned', 'viewable', 'name', 'mime_type', 'enrichment', 'image', 'image_class', 'animation_url', 'animation_class', 'collection_name', 'doc_keys'])
summ = []
for cnd in cands:
    c = cnd['contract']; o = 0; rows = []
    while True:
        items = gql(c, o)
        rows += items; o += len(items)
        if len(items) < 100: break
    cnt = Counter(); hosts = Counter(); burned = 0
    for t in rows:
        m = t.get('metadata') or {}; oj = m.get('origin_json') or {}
        if isinstance(oj, str):
            try: oj = json.loads(oj)
            except Exception: oj = {}
        if not isinstance(oj, dict): oj = {}
        img, anim = oj.get('image'), oj.get('animation_url')
        ic, ac = cls(img), cls(anim)
        if t.get('burned'): burned += 1
        cnt[(ic, ac)] += 1
        for v in (img, anim):
            if v and str(v).startswith('http'): hosts[urllib.parse.urlparse(str(v)).netloc.lower()] += 1
        tw.writerow([c, cnd['opensea_slug'], t['token_number'], t.get('burned'), t.get('viewable'), oj.get('name', ''), '',
                     m.get('enrichment_level') or '', img or '', ic, anim or '', ac, oj.get('collection_name', ''), ' '.join(sorted(oj))[:200]])
    dep_cdn = sum(n for (ic, ac), n in cnt.items() if 'ff-cdn' in (ic, ac))
    dep_3p = sum(n for (ic, ac), n in cnt.items() if 'third-party' in (ic, ac) and 'ff-cdn' not in (ic, ac))
    all_ipfs = sum(n for (ic, ac), n in cnt.items() if ic in ('ipfs', 'none') and ac in ('ipfs', 'none') and (ic, ac) != ('none', 'none'))
    no_doc = cnt[('none', 'none')]
    summ.append({'contract': c, 'opensea_slug': cnd['opensea_slug'], 'tokens': len(rows), 'burned': burned, 'all_ipfs': all_ipfs, 'depends_ff_cdn': dep_cdn, 'depends_third_party': dep_3p, 'no_doc_media': no_doc,
                 'classes': '; '.join(f'{ic}/{ac}:{n}' for (ic, ac), n in cnt.most_common()), 'hosts': '; '.join(f'{h}:{n}' for h, n in hosts.most_common(5))})
    print(f"{cnd['opensea_slug'][:44]:44s} {c[:10]} tokens={len(rows):5d} ipfs={all_ipfs:5d} ff-cdn={dep_cdn:4d} 3p={dep_3p:4d} nodoc={no_doc:4d} | {summ[-1]['hosts'][:90]}", flush=True)
sw = csv.DictWriter(open(sys.argv[3], 'w', newline=''), fieldnames=list(summ[0]), lineterminator='\n'); sw.writeheader(); sw.writerows(summ)
T = sum(s['tokens'] for s in summ); print(f"\nTOTAL tokens={T} all_ipfs={sum(s['all_ipfs'] for s in summ)} depends_ff_cdn={sum(s['depends_ff_cdn'] for s in summ)} third_party={sum(s['depends_third_party'] for s in summ)} no_doc={sum(s['no_doc_media'] for s in summ)}")
