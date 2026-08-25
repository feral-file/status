#!/usr/bin/env python3
"""Generate replacement ERC-721 metadata directories for a FeralfileExhibitionV2
(Ethereum) series whose animation_url / image point at broken or off-IPFS files.

  python3 gen.py [--tokens ../rewilded_eth_tokens.csv] [--classes HLS,CDN]

Reads the token table (edition,class,token_id,metadata_ipfs_cid,animation_url),
fetches each token's current metadata.json from the gateway into src/ (cached),
rewrites ONLY `animation_url` and `image` to the CIDs below, and writes one
directory per token under dirs/<edition>/metadata.json (the contract's
tokenURI shape). Then run ./pin.sh on the IPFS tunnel → result.csv.

Byte format mirrors what the server emits (compact, sorted keys, Go-style
HTML escaping) so a reviewer can diff src/ vs dirs/ and see only two lines.
"""
import argparse, csv, json, os, sys, urllib.request

GATEWAY = 'https://ipfs.bitmark.com/ipfs/'
VIDEO = 'ipfs://QmV6a8NCQDTq1pMddqgMNg9xutBkp7oa2EJTspi5tH7z6C'   # preview.mp4, SHA-256 b0471b76… (== CDN 1679631642/preview.mp4)
IMAGE = 'ipfs://QmUPxh15j9tss7FpUUT5WhLmadA24yVf4qrMe1FbinnW76'   # series image already used by the other editions

ap = argparse.ArgumentParser()
ap.add_argument('--tokens', default='../rewilded_eth_tokens.csv')
ap.add_argument('--classes', default='HLS,CDN', help='which `class` values to rewrite')
a = ap.parse_args()
here = os.path.dirname(os.path.abspath(__file__))
os.chdir(here)
os.makedirs('src', exist_ok=True); os.makedirs('dirs', exist_ok=True)

def go_json(o):
    s = json.dumps(o, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    return s.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')

classes = set(a.classes.split(','))
rows = [r for r in csv.DictReader(open(a.tokens)) if r['class'] in classes]
plan = []
for r in sorted(rows, key=lambda r: int(r['edition'])):
    src = f"src/{r['metadata_ipfs_cid']}.json"
    if not os.path.exists(src):
        open(src, 'wb').write(urllib.request.urlopen(f"{GATEWAY}{r['metadata_ipfs_cid']}/metadata.json", timeout=120).read())
    m = json.load(open(src))
    if str(m.get('edition_index')) != r['edition']:
        sys.exit(f"edition mismatch for token …{r['token_id'][-6:]}: metadata says {m.get('edition_index')}, table says {r['edition']}")
    old_anim, old_img = m['animation_url'], m['image']
    m['animation_url'] = VIDEO; m['image'] = IMAGE
    d = f"dirs/{int(r['edition']):03d}"; os.makedirs(d, exist_ok=True)
    open(f'{d}/metadata.json', 'w').write(go_json(m))
    plan.append([r['edition'], r['class'], r['token_id'], r['metadata_ipfs_cid'], old_anim, old_img, d])
w = csv.writer(open('plan.csv', 'w')); w.writerow(['edition', 'class', 'token_id', 'old_metadata_cid', 'old_animation_url', 'old_image', 'dir']); w.writerows(plan)
print(f'{len(plan)} metadata dirs written under dirs/; plan.csv updated')
