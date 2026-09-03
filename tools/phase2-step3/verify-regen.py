#!/usr/bin/env python3
"""Independent verification of the phase-2 regenerated metadata docs.

Deliberately does NOT reuse the regen tools' mapping logic — it proves the
outputs from the artifacts alone:

A. Doc integrity (per token):
   1. reverse-substitution proof: take the NEW doc bytes, substitute each
      new media value back with the old one — the result must equal the
      ORIGINAL on-chain doc byte-for-byte. That guarantees nothing outside
      the media values changed, at the byte level.
   2. JSON double-check: identical key sets; every non-media value
      deep-equal; every changed media value starts with ipfs://; a media
      value that was NOT CDN-class must be byte-identical to the original.

B. Media 1:1 content proof (deduped across tokens):
   for every (old CDN URL -> new ipfs URL) pair, fetch BOTH — the old from
   the CDN exactly as published (params intact, relative paths get the CDN
   host), the new via ipfs.feralfile.com — and compare: full byte equality
   up to 4 MB, else first 64 KB + Content-Length equality.

Usage:
  python3 tools/phase2-step3/verify-regen.py v4 \
      --audit ops/cdn-retirement-phase2/step0/v4_audit_crystalline.csv \
      --src ops/cdn-retirement-phase2/step3/src \
      --out-dir ops/cdn-retirement-phase2/step3/crystalline-newdir \
      --report ops/cdn-retirement-phase2/step3/verify_crystalline.csv

  python3 tools/phase2-step3/verify-regen.py v3 \
      --plan ops/cdn-retirement-phase2/step3/v3-docs/plan.csv \
      --src ops/cdn-retirement-phase2/step3/v3-src \
      --report ops/cdn-retirement-phase2/step3/verify_v3.csv

Exit 1 on any doc or media mismatch.
"""
import argparse, csv, json, os, sys, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

MEDIA_KEYS = ('image', 'animation_url')
CDN_HOSTS = ('cdn.feralfileassets.com', 'imagedelivery.net')
CDN_PREFIX = 'https://cdn.feralfileassets.com/'
GW = 'https://ipfs.feralfile.com/ipfs/'
FULL_CMP_MAX = 4 * 1024 * 1024
HEAD_CMP = 64 * 1024

ap = argparse.ArgumentParser()
ap.add_argument('mode', choices=['v4', 'v3'])
ap.add_argument('--audit')
ap.add_argument('--plan')
ap.add_argument('--src', required=True)
ap.add_argument('--out-dir')
ap.add_argument('--report', required=True)
ap.add_argument('--workers', type=int, default=8)
ap.add_argument('--timeout', type=float, default=120)
a = ap.parse_args()

def esc_variants(s):
    """The byte forms a Go-JSON document may use for this string."""
    plain = s.encode()
    esc = s
    for ch, rep in (('&', '\\u0026'), ('<', '\\u003c'), ('>', '\\u003e')):
        esc = esc.replace(ch, rep)
    return [plain, esc.encode()] if esc != s else [plain]

def find_form(raw, s):
    for b in esc_variants(s):
        if raw.count(b):
            return b
    return None

def is_cdn(v):
    return bool(v) and (any(h in v for h in CDN_HOSTS) or v.startswith(('previews/', 'thumbnails/')))

# --- token list: (token_id, old_raw_path, new_raw_path) ----------------------
toks = []
if a.mode == 'v4':
    if not (a.audit and a.out_dir):
        sys.exit('v4 mode needs --audit and --out-dir')
    for r in csv.DictReader(open(a.audit)):
        if r['chain_needs_fix'] == 'True':
            toks.append((r['token_id'],
                         os.path.join(a.src, r['doc_cid']),
                         os.path.join(a.out_dir, r['token_id'])))
else:
    if not a.plan:
        sys.exit('v3 mode needs --plan')
    for r in csv.DictReader(open(a.plan)):
        toks.append((r['token_id'],
                     os.path.join(a.src, r['old_metadata_cid'] + '.json'),
                     r['doc_file']))
print(f'{a.mode}: verifying {len(toks)} docs', flush=True)

lock = threading.Lock()
doc_fail, media_pairs = [], {}   # (old_abs_url, new_gw_url) -> [token,...]
counts = {'ok': 0}

def old_to_abs(v):
    return v if v.startswith('http') else CDN_PREFIX + v

def check_doc(item):
    t, old_p, new_p = item
    try:
        old_raw = open(old_p, 'rb').read()
        new_raw = open(new_p, 'rb').read()
        old_d, new_d = json.loads(old_raw), json.loads(new_raw)
        errs = []
        if set(old_d) != set(new_d):
            errs.append(f'key sets differ: {sorted(set(old_d) ^ set(new_d))}')
        pairs = []
        for k in set(old_d) | set(new_d):
            ov, nv = old_d.get(k), new_d.get(k)
            if k in MEDIA_KEYS:
                if is_cdn(ov or ''):
                    if not (isinstance(nv, str) and nv.startswith('ipfs://')):
                        errs.append(f'{k}: CDN value not replaced with ipfs:// ({str(nv)[:60]})')
                    else:
                        pairs.append((k, ov, nv))
                elif ov != nv:
                    errs.append(f'{k}: non-CDN media value changed ({str(ov)[:40]} -> {str(nv)[:40]})')
            elif ov != nv:
                errs.append(f'non-media key changed: {k}')
        # reverse-substitution byte proof
        rev = new_raw
        for k, ov, nv in {(k, o, n) for k, o, n in pairs}:
            nb = find_form(rev, nv)
            ob = find_form(old_raw, ov)
            if nb is None or ob is None:
                errs.append(f'{k}: value bytes not found for reverse substitution')
                continue
            rev = rev.replace(nb, ob)
        if rev != old_raw:
            errs.append('reverse-substituted bytes != original doc bytes')
        with lock:
            if errs:
                doc_fail.append((t, '; '.join(errs)[:300]))
            else:
                counts['ok'] += 1
                for k, ov, nv in pairs:
                    key = (old_to_abs(ov), nv)
                    media_pairs.setdefault(key, []).append(t)
            if (counts['ok'] + len(doc_fail)) % 1000 == 0:
                print(f"  docs {counts['ok'] + len(doc_fail)}/{len(toks)}", flush=True)
    except Exception as e:
        with lock:
            doc_fail.append((t, f'{type(e).__name__}: {str(e)[:150]}'))

with ThreadPoolExecutor(max_workers=a.workers) as ex:
    list(ex.map(check_doc, toks))
print(f'A. doc integrity: {counts["ok"]} ok, {len(doc_fail)} FAILED', flush=True)
for t, e in doc_fail[:10]:
    print('  DOC-FAIL', t[-12:], e)

# --- B. media content 1:1 ----------------------------------------------------
def ipfs_to_gw(nv):
    rest = nv[len('ipfs://'):]
    path = rest.split('?', 1)[0]
    return GW + urllib.parse.quote(path, safe='/')

def fetch(url, rng=None):
    req = urllib.request.Request(url, headers={'User-Agent': 'phase2-verify',
                                               **({'Range': rng} if rng else {})})
    r = urllib.request.urlopen(req, timeout=a.timeout)
    body = r.read()
    total = r.headers.get('Content-Range', '').split('/')[-1] or r.headers.get('Content-Length', '')
    return body, total

media_fail = []
done_n = [0]
def check_media(item):
    (old_url, new_v), owners = item
    gw_url = ipfs_to_gw(new_v)
    err = None
    for attempt in range(3):
        try:
            ob, ot = fetch(old_url, 'bytes=0-%d' % (HEAD_CMP - 1))
            nb, nt = fetch(gw_url, 'bytes=0-%d' % (HEAD_CMP - 1))
            if ob != nb:
                err = 'head bytes differ'; break
            if ot and nt and ot != nt:
                err = f'length differs cdn={ot} ipfs={nt}'; break
            size = int(ot or nt or 0)
            if 0 < size <= FULL_CMP_MAX and size > HEAD_CMP:
                fb, _ = fetch(old_url)
                gb, _ = fetch(gw_url)
                if fb != gb:
                    err = 'full bytes differ'; break
            err = None; break
        except Exception as e:
            err = f'{type(e).__name__}: {str(e)[:100]}'
            time.sleep(3 * (attempt + 1))
    with lock:
        done_n[0] += 1
        if err:
            media_fail.append((old_url[:90], new_v[:70], err, len(owners)))
            print(f'  MEDIA-FAIL {err} | {old_url[:70]}', flush=True)
        if done_n[0] % 500 == 0:
            print(f'  media {done_n[0]}/{len(media_pairs)}', flush=True)

print(f'B. media pairs to content-check: {len(media_pairs)} (deduped)', flush=True)
with ThreadPoolExecutor(max_workers=a.workers) as ex:
    list(ex.map(check_media, sorted(media_pairs.items())))

os.makedirs(os.path.dirname(a.report) or '.', exist_ok=True)
with open(a.report, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['kind', 'id_or_url', 'detail'])
    for t, e in doc_fail:
        w.writerow(['doc', t, e])
    for ou, nv, e, n in media_fail:
        w.writerow(['media', ou, f'{e} (affects {n} tokens; new={nv})'])
print(f'\nRESULT {a.mode}: docs {counts["ok"]}/{len(toks)} ok, doc-fails {len(doc_fail)}; '
      f'media pairs {len(media_pairs)-len(media_fail)}/{len(media_pairs)} ok, media-fails {len(media_fail)}')
print(f'report: {a.report}')
sys.exit(1 if (doc_fail or media_fail) else 0)
