#!/usr/bin/env python3
"""Generate replacement TZIP-21 metadata JSONs for Tezos FA2 tokens whose
artifactUri points at an HLS master playlist (unplayable from IPFS).

  python3 gen.py [--tokens tokens.csv]

tokens.csv: token_id,metadata_uri  (current token_info[""] per token — from
tzkt /v1/contracts/<KT1>/bigmaps/token_metadata/keys). For each token the
current JSON is fetched into src/ (cached), `artifactUri` and `formats[0]`
are rewritten per the OLD→NEW table below, everything else is byte-preserved,
and the result is written to files/<token_id>.json. Then ./pin.sh → result.csv.
"""
import argparse, csv, json, os, sys, urllib.request

GATEWAY = 'https://ipfs.feralfile.com/ipfs/'
NEW = {  # old HLS master CID -> (replacement MP4 CID, byte size); MP4 = the series' CDN preview.mp4, SHA-256 verified
    'QmRGwoEnB4inboActrRsNAEiJzXL8LUwLrCYcUCgAEBxMQ': ('bafybeiagkwrb4av4e27x2fihhwl3q3oa5uqp42wynjd5vksfiswouz4tka', 21528778),
    'Qmf8bvobDWMTmauvhgFKWNhZKUe4ufDY16a6qk1KLSgM74': ('bafybeifu35t24hzfbq7voe5n3xe4sbclckrs6vsn2b5xixtv3togk4yi2u', 181715832),
}

ap = argparse.ArgumentParser(); ap.add_argument('--tokens', default='tokens.csv'); a = ap.parse_args()
os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.makedirs('src', exist_ok=True); os.makedirs('files', exist_ok=True)

def go_json(o):
    s = json.dumps(o, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    return s.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')

plan = []
for t in csv.DictReader(open(a.tokens)):
    cid = t['metadata_uri'].replace('ipfs://', '')
    src = f'src/{cid}.json'
    if not os.path.exists(src):
        open(src, 'wb').write(urllib.request.urlopen(f'{GATEWAY}{cid}', timeout=120).read())
    m = json.load(open(src))
    old = m['artifactUri'].replace('ipfs://', '')
    if old not in NEW: sys.exit(f"token …{t['token_id'][-6:]}: artifactUri {old} not in the OLD→NEW table")
    new, size = NEW[old]
    fm = m['formats']
    if not (isinstance(fm, list) and fm and fm[0]['uri'] == f'ipfs://{old}'): sys.exit(f"token …{t['token_id'][-6:]}: formats[0] is not the artifact")
    m['artifactUri'] = f'ipfs://{new}'
    fm[0] = {'fileSize': size, 'mimeType': 'video/mp4', 'uri': f'ipfs://{new}'}
    open(f"files/{t['token_id']}.json", 'w').write(go_json(m))
    plan.append([t['token_id'], m.get('editionIndex'), old[:12], cid, f"files/{t['token_id']}.json"])
w = csv.writer(open('plan.csv', 'w')); w.writerow(['token_id', 'edition_index', 'old_artifact', 'old_metadata_cid', 'file']); w.writerows(plan)
print(f'{len(plan)} files written under files/; plan.csv updated')
