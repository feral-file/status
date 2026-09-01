#!/usr/bin/env python3
"""Generate replacement metadata directories for V2 tokens whose on-chain
metadata points at non-IPFS media (goal 2 of ops/bitmark-cdn-retirement.md).

  python3 gen.py --audit audit.csv --export export.csv [--contract 0x…] [--out dirs]

Inputs
  audit.csv   from audit.py — only rows with needs_fix=1 and no error are used;
              onchain_cid is the directory to rewrite (never the DB's cid).
  export.csv  from db/export-v2-cdn-tokens.sql — supplies medium and the
              ipfs_reference targets (preview_ipfs_uri, thumbnail_ipfs_uri).

Rewrite rule = swap.GenerateArtworkSwappingMetadata (feral-file-server):
  image          = thumbnail_ipfs_uri
  animation_url  = preview_ipfs_uri   (video, audio, software, animated gif, 3d)
  image          = preview_ipfs_uri   (image medium; animation_url untouched)
  image          = thumbnail_ipfs_uri (txt, pdf, unknown — server default branch; animation_url untouched)
Every other key is byte-preserved (compact, sorted keys, Go HTML escaping — the
server's json.Marshal shape). A token is refused (listed in blocked.csv, not
written) if a needed reference is missing or not ipfs://, if the audit's
onchain_cid no longer matches the cached metadata, or edition_index disagrees.

Output
  dirs/<contract>/<token_id>/metadata.json
  plan.csv  contract,edition,token_id,old_metadata_cid,old_animation_url,old_image,new_animation_url,new_image,dir,token_id_db,db_cid,source
            token_id = decimal for the chain; token_id_db = the DB's own string (decimal or 64-hex) for SQL;
            old_metadata_cid = what is on chain (update-token-uri's precondition); db_cid = swaps.ipfs_cid (SQL's precondition);
            source = chain | db (db: the chain's dir is unservable, so the DB's metadata is the source; the media are
            still rewritten to the CURRENT ipfs_reference — Primordium 2026-08-28: the 2023 DB metadata pointed at 2022
            previews superseded in 2024-09, while the contract's other 51 tokens point at the 2024-09 ones)
            changed_params = old-URL params absent/different on the new URI (old→new), only ever those named in --allow-param-diff
DB ≠ chain is accepted only when the two metadata differ in nothing but timestamp / prev_provenance.
Legacy 2021 metadata (no edition_index) is checked by the trailing "#N" of name.
  blocked.csv contract,token_id,reason
Diff check: `diff <(python3 -m json.tool src/<old>.json) <(python3 -m json.tool dirs/<c>/<t>/metadata.json)` → only the rewritten keys change.
"""
import argparse, csv, json, os, re, sys, urllib.parse, urllib.request

ANIM_MEDIA = {'video', 'audio', 'software', 'animated gif', '3d'}
GATEWAY = 'https://ipfs.bitmark.com/ipfs/'

ap = argparse.ArgumentParser()
ap.add_argument('--audit', default='audit.csv'); ap.add_argument('--export', required=True)
ap.add_argument('--contract', help='restrict to one contract'); ap.add_argument('--out', default='dirs')
ap.add_argument('--allow-param-diff', default='', help='comma list of query params that may be absent or differ on the new URI (edition_number never). Use only with evidence the work does not read them (e.g. grep its index.html/main.js for URLSearchParams); every such change is recorded in plan.csv changed_params')
a = ap.parse_args()
here = os.path.dirname(os.path.abspath(__file__)); os.chdir(here); os.makedirs('src', exist_ok=True)

def go_json(o):
    s = json.dumps(o, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    return s.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')

def is_ipfs(u): return bool(u) and u.startswith('ipfs://') and len(u) > len('ipfs://') and not u.startswith('ipfs://?')

DIFF_OK = {p for p in a.allow_param_diff.split(',') if p} - {'edition_number'}

def params_preserved(old, new, edition):
    """CDN URLs carried the parameters generative works read at runtime
    (?edition_number=…&blockchain=…). Every parameter on the old URL must be on
    the new ipfs:// URI with the same value, and edition_number (if present on
    either) must equal this token's edition. Returns None or a reason."""
    oq = urllib.parse.parse_qs(urllib.parse.urlparse(old or '').query)
    nq = urllib.parse.parse_qs(urllib.parse.urlparse(new).query)
    dropped = []
    for k, v in oq.items():
        if nq.get(k) == v: continue
        if k in DIFF_OK: dropped.append(f"{k}:{','.join(v)}→{','.join(nq.get(k, ['∅']))}"); continue
        return f'param {k}={v} on old URL not preserved on new {new!r}', None
    en = nq.get('edition_number') or oq.get('edition_number')
    if en and en != [str(edition)]: return f'edition_number param {en} ≠ token edition {edition}', None
    return None, ','.join(dropped)

def norm_id(t):
    t = t.strip()
    return t if t.isdigit() else (str(int(t, 16)) if len(t.replace('0x', '')) == 64 else t)
exp = {(r['contract'].lower(), norm_id(r['token_id'])): r for r in csv.DictReader(open(a.export))}
HARMLESS_DIFF = {'timestamp', 'prev_provenance'}   # re-generated metadata differs only here between DB and chain

def fetch(cid):
    p = f'src/{cid}.json'
    if not os.path.exists(p):
        raw = None
        for gw in (GATEWAY, 'https://ipfs.io/ipfs/'):
            try: raw = urllib.request.urlopen(urllib.request.Request(f'{gw}{cid}/metadata.json', headers={'User-Agent': 'v2-metadata-regen/gen'}), timeout=120).read(); break
            except Exception: pass
        if raw is None: return None
        open(p, 'wb').write(raw)
    return json.load(open(p))

def edition_of(m):
    """edition_index, or for 2021 legacy metadata the trailing '#N' of name."""
    if str(m.get('edition_index', '')) != '': return str(m['edition_index'])
    mm = re.search(r'#(\d+)\s*$', m.get('name', ''))
    return mm.group(1) if mm else None

audit = [r for r in csv.DictReader(open(a.audit))
         if r['needs_fix'] == '1' and not r['error']
         or (r['error'].startswith('fetch failed') and r.get('db_cid') and r['db_cid'] != r['onchain_cid'])]  # chain dir unservable → adopt the DB's regenerated version
if a.contract: audit = [r for r in audit if r['contract'].lower() == a.contract.lower()]
plan, blocked = [], []
for r in sorted(audit, key=lambda r: (r['contract'], int(r['token_id']))):
    key = (r['contract'].lower(), r['token_id']); e = exp.get(key)
    if not e: blocked.append([*key, 'not in DB export']); continue
    db_cid = e['old_metadata_cid']; source = 'chain'
    m = fetch(r['onchain_cid']) if not r['error'] else None
    if db_cid != r['onchain_cid']:
        dbm = fetch(db_cid)
        if dbm is None: blocked.append([*key, f'DB cid {db_cid} ≠ chain {r["onchain_cid"]} and DB metadata not fetchable']); continue
        if m is None:
            m = dbm; source = 'db'   # chain points at an unservable dir; the DB's regenerated metadata is the only copy
        else:
            d = {k for k in set(m) | set(dbm) if m.get(k) != dbm.get(k)} - HARMLESS_DIFF
            if d: blocked.append([*key, f'DB cid {db_cid} ≠ chain {r["onchain_cid"]} with real differences {sorted(d)} — reconcile first']); continue
    if m is None: blocked.append([*key, f'chain metadata {r["onchain_cid"]} not fetchable']); continue
    ed = edition_of(m)
    if ed != str(e['edition']): blocked.append([*key, f"metadata edition {ed} ≠ DB edition {e['edition']}"]); continue
    med, prev, thumb = e['medium'], e['preview_ipfs_uri'], e['thumbnail_ipfs_uri']
    old_an, old_im = m.get('animation_url'), m.get('image')
    if med == 'image':
        if not is_ipfs(prev): blocked.append([*key, f'image medium: preview reference missing/not ipfs ({prev!r}) — EnsureIPFSReferenceByURI first']); continue
        m['image'] = prev
        if old_an is not None and not is_ipfs(old_an): blocked.append([*key, f'image medium but animation_url set to non-ipfs {old_an!r} — decide by hand']); continue
    elif med in ANIM_MEDIA:
        if not is_ipfs(prev): blocked.append([*key, f'preview reference missing/not ipfs ({prev!r}) — EnsureIPFSReferenceByURI first']); continue
        if not is_ipfs(thumb): blocked.append([*key, f'thumbnail reference missing/not ipfs ({thumb!r}) — EnsureIPFSReferenceByURI first']); continue
        m['animation_url'] = prev; m['image'] = thumb
    else:  # server default branch (txt, pdf, unknown): only image = thumbnail; animation_url untouched
        if not is_ipfs(thumb): blocked.append([*key, f'thumbnail reference missing/not ipfs ({thumb!r}) — EnsureIPFSReferenceByURI first']); continue
        m['image'] = thumb
        if old_an is not None and not is_ipfs(old_an): blocked.append([*key, f'medium {med!r} but animation_url set to non-ipfs {old_an!r} — decide by hand']); continue
    if m.get('animation_url') == old_an and m.get('image') == old_im and source == 'chain': blocked.append([*key, 'no change after rewrite']); continue
    # source == 'db' with no change is fine: the DB's regenerated metadata already matched ipfs_reference; a fresh dir is still registered
    if source == 'db':
        # nothing on chain to preserve (its dir is unservable); the DB's stale params are recorded, not enforced
        oq = urllib.parse.urlparse(old_an or '').query
        dropped = f'db-source: old params [{oq}] not carried; new = ipfs_reference' if oq else ''
    else:
        why, drop_a = params_preserved(old_an, m['animation_url'], e['edition']) if 'animation_url' in m else (None, '')
        if not why: why, drop_i = params_preserved(old_im, m['image'], e['edition'])
        if why: blocked.append([*key, why]); continue
        dropped = ';'.join(x for x in (drop_a, drop_i) if x)
    d = f"{a.out}/{r['contract'].lower()}/{r['token_id']}"; os.makedirs(d, exist_ok=True)
    open(f'{d}/metadata.json', 'w').write(go_json(m))
    plan.append([r['contract'].lower(), e['edition'], r['token_id'], r['onchain_cid'], old_an or '', old_im or '', m.get('animation_url', ''), m['image'], d, e['token_id'].strip(), db_cid, source, dropped])
with open('plan.csv', 'w') as f:
    w = csv.writer(f, lineterminator='\n'); w.writerow('contract,edition,token_id,old_metadata_cid,old_animation_url,old_image,new_animation_url,new_image,dir,token_id_db,db_cid,source,changed_params'.split(',')); w.writerows(plan)
with open('blocked.csv', 'w') as f:
    w = csv.writer(f, lineterminator='\n'); w.writerow(['contract', 'token_id', 'reason']); w.writerows(blocked)
print(f'{len(plan)} metadata dirs written under {a.out}/ (plan.csv); {len(blocked)} blocked (blocked.csv)')
sys.exit(1 if blocked else 0)
