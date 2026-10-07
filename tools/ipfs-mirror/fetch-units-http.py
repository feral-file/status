#!/usr/bin/env python3
"""Fetch CDN pin units over HTTP into the local mirror tree, for when the
origin bucket is not at hand but a host still serves the same keys.

`mirror-add-pin.sh` normally syncs each unit from the origin bucket. The CDN
moved (2026-10: `cdn.feralfileassets.com` no longer resolves; the same keys
are served by `cdn.artworks.feralfile.io`), and plain HTTP cannot list a
directory — so this builds each unit from what can be known:

  - bare-file unit   → that one object;
  - directory unit   → the file the tokens name (`sample_url` path), or
    `index.html` when they name the directory itself, then a crawl: every
    relative reference found in fetched HTML / CSS / JS (src, href, url(…),
    quoted paths with an asset extension) is tried against the referencing
    file's directory and the unit root; hits are fetched and crawled in turn.

The crawl cannot see a file that is only ever named by code at run time
(a computed path). Each directory's file list is printed and recorded in
`<work>/manifest.csv` (unit, path, bytes, sha256, url) — read it, and open the
work from the gateway after pinning (`verify-docs.py`, then a browser). If the
bucket can be listed, prefer `mirror-add-pin.sh` with BUCKET.

  python3 tools/ipfs-mirror/fetch-units-http.py --dirs cdn_dirs.csv \
      --base https://cdn.artworks.feralfile.io/ --work ./mirror
  LOCAL=1 WORK=./mirror ./tools/ipfs-mirror/mirror-add-pin.sh cdn_dirs.csv dir_cids.csv

Layout written = the one mirror-add-pin.sh expects: `<work>/<key>/…` for a
directory unit, `<work>/<key>/<basename>` for a bare file. Resumable: files
already on disk with the size the host reports are not fetched again.
Exit 1 if any unit's seed file is missing.
"""
import argparse, csv, hashlib, os, posixpath, re, sys, time, urllib.error, urllib.parse, urllib.request

CDN_PREFIX = 'https://cdn.feralfileassets.com/'
ASSET_EXT = ('js|mjs|css|html?|json|png|jpe?g|gif|svg|webp|avif|ico|mp4|webm|mov|m4v|mp3|wav|ogg|m4a|flac|glb|gltf|obj|mtl|fbx|'
             'hdr|exr|ktx2?|bin|wasm|data|woff2?|ttf|otf|eot|txt|csv|xml|frag|vert|glsl|wgsl|map|pdf|zip')
REF_RES = [
    re.compile(r'''(?:src|href|poster|data-src)\s*=\s*["']([^"'#?]+)''', re.I),
    re.compile(r'''url\(\s*["']?([^"')#?]+)''', re.I),
    re.compile(r'''["'`]((?:\./|\.\./)?[\w\-./%@ ]+\.(?:''' + ASSET_EXT + r'''))["'`?#]''', re.I),
]
TEXT_EXT = ('.html', '.htm', '.js', '.mjs', '.css', '.json', '.svg', '.gltf', '.xml', '.txt')

ap = argparse.ArgumentParser()
ap.add_argument('--dirs', required=True)
ap.add_argument('--base', required=True, help='host serving the same keys, e.g. https://cdn.artworks.feralfile.io/')
ap.add_argument('--work', required=True)
ap.add_argument('--max-files', type=int, default=5000, help='safety cap per directory unit')
a = ap.parse_args()
BASE = a.base.rstrip('/') + '/'

# `Accept: */*` matters: without an Accept header Cloudflare rewrites HTML on
# the way out (appends its Web Analytics beacon <script>, +367 bytes, measured
# 2026-10-05) — those are not the origin's bytes. Any fetched file carrying the
# beacon host is refused below.
HEADERS = {'User-Agent': 'ipfs-mirror/fetch-units-http', 'Accept': '*/*'}
INJECTED = b'static.cloudflareinsights.com'

def request(url, method='GET'):
    last = None
    for attempt in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, method=method, headers=HEADERS), timeout=120)
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):
                return None
            last = e
        except Exception as e:
            last = e
        time.sleep(2 + 3 * attempt)
    sys.exit(f'giving up on {url}: {last}')

def fetch(key, dst):
    """Download BASE+key to dst unless already complete. Returns size, or None if the host has no such key."""
    url = BASE + urllib.parse.quote(key, safe='/')
    head = request(url, 'HEAD')
    if head is None:
        return None
    want = head.headers.get('Content-Length')
    if os.path.exists(dst) and want and os.path.getsize(dst) == int(want):
        return int(want)
    res = request(url)
    if res is None:
        return None
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + '.part'
    with open(tmp, 'wb') as f:
        while True:
            chunk = res.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    if want and os.path.getsize(tmp) != int(want):
        sys.exit(f'short read on {url}: {os.path.getsize(tmp)} of {want} bytes')
    if os.path.getsize(tmp) < 20 * 1024 * 1024 and INJECTED in open(tmp, 'rb').read():
        sys.exit(f'{url}: response carries the Cloudflare analytics beacon — edge-rewritten, not origin bytes; not kept')
    os.replace(tmp, dst)
    return os.path.getsize(dst)

def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

def refs(text):
    out = set()
    for rx in REF_RES:
        for m in rx.finditer(text):
            r = m.group(1).strip()
            if r and not re.match(r'^(?:[a-z][a-z0-9+.-]*:|//|/|#)', r, re.I):   # relative only
                out.add(urllib.parse.unquote(r))
    return out

manifest, missing_seed = [], []
units = list(csv.DictReader(open(a.dirs)))
for i, r in enumerate(units, 1):
    unit = r['dir_or_file']
    if not unit.startswith(CDN_PREFIX):
        print(f'[{i}/{len(units)}] not a CDN unit, skipped: {unit}'); continue
    key = unit[len(CDN_PREFIX):]
    dst = os.path.join(a.work, key.rstrip('/'))
    if not unit.endswith('/'):
        n = fetch(key, os.path.join(dst, os.path.basename(key)))
        if n is None:
            missing_seed.append(unit); print(f'[{i}/{len(units)}] MISSING at {BASE}: {key}'); continue
        manifest.append([unit, os.path.basename(key), n, sha256(os.path.join(dst, os.path.basename(key))), BASE + key])
        print(f'[{i}/{len(units)}] file {key}  {n:,} bytes')
        continue
    sample = r.get('sample_url', '').split('?', 1)[0]
    seed = sample[len(unit):] if sample.startswith(unit) and len(sample) > len(unit) else 'index.html'
    queue, seen, got, tried_404 = [seed], {seed}, {}, set()
    while queue:
        rel = queue.pop(0)
        local = os.path.join(dst, rel)
        n = fetch(key + rel, local)
        if n is None:
            tried_404.add(rel); continue
        got[rel] = n
        if len(got) > a.max_files:
            sys.exit(f'{unit}: more than {a.max_files} files — raise --max-files if that is right')
        if rel.lower().endswith(TEXT_EXT) and n < 20 * 1024 * 1024:
            text = open(local, 'rb').read().decode('utf-8', 'replace')
            for ref in refs(text):
                for cand in {posixpath.normpath(posixpath.join(posixpath.dirname(rel), ref)), posixpath.normpath(ref)}:
                    if cand.startswith('..') or cand in seen:
                        continue
                    seen.add(cand); queue.append(cand)
    if seed not in got:
        missing_seed.append(unit); print(f'[{i}/{len(units)}] MISSING seed {seed} at {BASE}{key}'); continue
    for rel, n in sorted(got.items()):
        manifest.append([unit, rel, n, sha256(os.path.join(dst, rel)), BASE + key + rel])
    print(f'[{i}/{len(units)}] dir  {key}  {len(got)} files, {sum(got.values()):,} bytes'
          f'  (seed {seed}; {len(tried_404)} guessed paths not on the host)')
    for rel, n in sorted(got.items()):
        print(f'      {n:>12,}  {rel}')

os.makedirs(a.work, exist_ok=True)
with open(os.path.join(a.work, 'manifest.csv'), 'w', newline='') as f:
    w = csv.writer(f, lineterminator='\n')
    w.writerow(['unit', 'path', 'bytes', 'sha256', 'url']); w.writerows(manifest)
print(f'\n{len(manifest)} files, {sum(m[2] for m in manifest):,} bytes → {a.work} (manifest.csv)')
if missing_seed:
    sys.exit(f'{len(missing_seed)} unit(s) not served by {BASE}')
