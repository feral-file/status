#!/usr/bin/env python3
"""filum (Truth 0xBb12686c…, V4, 128 tokens): build the permanent fix locally, with proof.

Problem (ops/cdn-retirement-phase2.md § Pending decisions): the on-chain docs already
point animation_url at an IPFS artwork dir, but the served version is a CDN copy behind
the per-artwork `alternativePreviewURI` overlay, and the ONLY difference is 7
`crossorigin="anonymous"` attributes in index.html (load-bearing for WebGL readPixels).

This tool, entirely offline and deterministic (`ipfs add -n`, CIDv0, default chunker —
the same flags that reproduce BOTH current dirs bit-for-bit):
  1. builds the patched artwork dir = IPFS bytes + the CDN index.html, proving the CDN
     index.html equals the IPFS one with exactly the 7 attributes inserted;
  2. rewrites the 128 filum docs, changing only the animation_url dir CID
     (byte-preserving; reverse-substitution proof + JSON equality on every other key);
  3. assembles the new tokenId-named base dir (768 docs byte-identical + 128 rewritten)
     and computes its CID — the value for setTokenBaseURI.
Nothing is uploaded; pin-and-verify.sh (operator, tunnel) adds the two dirs on prod-02
and asserts the CIDs match what is recorded here.

Usage: python3 tools/metadata-regen/filum-build.py --art-ipfs <dir> --art-cdn <dir> \
           --truth-src <dir of 896 docs> --out ops/cdn-retirement-phase2/filum
"""
import argparse, csv, json, os, shutil, subprocess, sys

OLD_ART = 'Qma2VZMhsrMjrbCZcJQXuF71XTwRdL45EPH97KC8BHo8Pd'
OLD_BASE = 'QmQjzvrvZjzNGiqQhTGsiHeTpb9FmEcjCVWxVySf5FANC1'
CONTRACT = '0xBb12686c360e9057be3CD031140035A705e19ceC'
ATTR = b' crossorigin="anonymous"'

ap = argparse.ArgumentParser()
ap.add_argument('--art-ipfs', required=True); ap.add_argument('--art-cdn', required=True)
ap.add_argument('--truth-src', required=True); ap.add_argument('--out', required=True)
a = ap.parse_args()
build = os.path.join(a.out, 'build'); os.makedirs(build, exist_ok=True)

def cid_of(path, recursive=False):
    cmd = ['ipfs', 'add', '-n', '-Q', '--cid-version', '0'] + (['-r'] if recursive else []) + [path]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
def fail(m): print('✗', m); sys.exit(1)
def ok(m): print('✓', m)

# ---- 0. the inputs must be the real thing
if cid_of(a.art_ipfs, True) != OLD_ART: fail('art-ipfs does not reproduce the on-chain artwork dir CID')
if cid_of(a.truth_src, True) != OLD_BASE: fail('truth-src does not reproduce the on-chain base dir CID')
ok(f'inputs reproduce {OLD_ART} and {OLD_BASE}')

# ---- 1. patched artwork dir
ipfs_idx = open(os.path.join(a.art_ipfs, 'index.html'), 'rb').read()
cdn_idx = open(os.path.join(a.art_cdn, 'index.html'), 'rb').read()
# apply the patch ourselves: every <img …> tag lacking crossorigin gets the attribute before '>'
import re
patched, n = re.subn(rb'(<img\b[^>]*?)(>)', lambda m: m.group(1) + ATTR + m.group(2) if b'crossorigin' not in m.group(1) else m.group(0), ipfs_idx)
if n != 7: fail(f'expected 7 <img> tags, patched {n}')
if patched != cdn_idx: fail('IPFS index.html + 7 attributes != CDN index.html — the CDN copy differs by more than the patch')
if len(cdn_idx) - len(ipfs_idx) != 7 * len(ATTR): fail('size delta is not 7 attributes')
ok(f'CDN index.html == IPFS index.html + 7×{ATTR.decode().strip()} ({7*len(ATTR)} bytes)')
art_new = os.path.join(build, 'art-new')
if os.path.exists(art_new): shutil.rmtree(art_new)
shutil.copytree(a.art_ipfs, art_new)
open(os.path.join(art_new, 'index.html'), 'wb').write(cdn_idx)
# every other file must be byte-identical between the three copies
for root, _, files in os.walk(a.art_ipfs):
    for f in files:
        rel = os.path.relpath(os.path.join(root, f), a.art_ipfs)
        if rel == 'index.html': continue
        b1 = open(os.path.join(a.art_ipfs, rel), 'rb').read(); b2 = open(os.path.join(a.art_cdn, rel), 'rb').read(); b3 = open(os.path.join(art_new, rel), 'rb').read()
        if not (b1 == b2 == b3): fail(f'{rel} differs between copies')
NEW_ART = cid_of(art_new, True)
ok(f'patched artwork dir CID {NEW_ART}')

# ---- 2. rewrite the 128 filum docs
base_new = os.path.join(build, 'base-new')
if os.path.exists(base_new): shutil.rmtree(base_new)
shutil.copytree(a.truth_src, base_new)
updates = []
n_filum = 0
for name in sorted(os.listdir(a.truth_src)):
    raw = open(os.path.join(a.truth_src, name), 'rb').read()
    doc = json.loads(raw)
    series = next((x['value'] for x in doc.get('attributes', []) if x.get('trait_type') == 'Series'), None)
    has_old = raw.count(OLD_ART.encode())
    if series != 'filum':
        if has_old: fail(f'{name}: non-filum doc references the filum artwork dir')
        continue
    n_filum += 1
    if has_old != 1: fail(f'{name}: old artwork CID occurs {has_old}× in bytes (expected exactly 1)')
    if not doc['animation_url'].startswith(f'ipfs://{OLD_ART}?'): fail(f'{name}: animation_url shape unexpected: {doc["animation_url"][:80]}')
    new_raw = raw.replace(OLD_ART.encode(), NEW_ART.encode())
    # proofs: reverse substitution → original bytes; JSON equal on every key but animation_url
    if new_raw.replace(NEW_ART.encode(), OLD_ART.encode()) != raw: fail(f'{name}: reverse substitution failed')
    nd = json.loads(new_raw)
    if set(nd) != set(doc): fail(f'{name}: key set changed')
    for k in doc:
        if k == 'animation_url':
            if nd[k] != doc[k].replace(OLD_ART, NEW_ART): fail(f'{name}: animation_url rewrote wrong')
        elif nd[k] != doc[k]: fail(f'{name}: non-media key changed: {k}')
    open(os.path.join(base_new, name), 'wb').write(new_raw)
    updates.append({'token_id': name, 'old_doc_cid': cid_of(os.path.join(a.truth_src, name)), 'new_doc_cid': cid_of(os.path.join(base_new, name)),
                    'old_animation_url': doc['animation_url'], 'new_animation_url': nd['animation_url'], 'image': doc.get('image', '')})
if n_filum != 128: fail(f'found {n_filum} filum docs, expected 128')
# untouched docs must be byte-identical
for name in os.listdir(a.truth_src):
    if name not in {u['token_id'] for u in updates}:
        if open(os.path.join(a.truth_src, name), 'rb').read() != open(os.path.join(base_new, name), 'rb').read(): fail(f'{name}: untouched doc changed')
NEW_BASE = cid_of(base_new, True)
ok(f'128 filum docs rewritten (animation_url dir only), 768 docs byte-identical; new base dir CID {NEW_BASE}')

# ---- 3. records
with open(os.path.join(a.out, 'doc_updates.csv'), 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(updates[0]), lineterminator='\n'); w.writeheader(); w.writerows(updates)
with open(os.path.join(a.out, 'cids.csv'), 'w', newline='') as f:
    w = csv.writer(f, lineterminator='\n'); w.writerow(['what', 'old_cid', 'new_cid'])
    w.writerow(['artwork_dir (animation_url target)', OLD_ART, NEW_ART]); w.writerow(['base_dir (tokenBaseURI)', OLD_BASE, NEW_BASE])
open(os.path.join(a.out, 'index.html.diff'), 'w').write(subprocess.run(['diff', '-u', os.path.join(a.art_ipfs, 'index.html'), os.path.join(art_new, 'index.html')], capture_output=True, text=True).stdout)
print(f'\nold artwork dir  {OLD_ART}\nnew artwork dir  {NEW_ART}\nold base dir     {OLD_BASE}\nnew base dir     {NEW_BASE}\n'
      f'records: {a.out}/cids.csv, doc_updates.csv (128 rows), index.html.diff; dirs to add on prod-02: {build}/art-new, {build}/base-new')
