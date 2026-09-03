#!/usr/bin/env python3
"""Prove every regenerated metadata.json differs from its source in NOTHING but
animation_url / image. Run after gen.py, before pin.sh.

  python3 check-dirs.py [plan.csv]

Per row: (1) key set and every non-media value identical to the source
(src/<old cid>.json, or the DB's cid for source=db); (2) the new media values
equal plan.csv; (3) the source bytes are reproduced exactly by the serializer
gen.py uses (so the output format is the server's, and the only bytes that can
change are the two values). Exit 1 on any failure.
"""
import csv, json, sys
def go_json(o):
    s = json.dumps(o, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    return s.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
rows = list(csv.DictReader(open(sys.argv[1] if len(sys.argv) > 1 else 'plan.csv')))
bad = []
for r in rows:
    src = r['old_metadata_cid'] if r['source'] == 'chain' else r['db_cid']
    raw = open(f'src/{src}.json', 'rb').read(); o = json.loads(raw); n = json.loads(open(f"{r['dir']}/metadata.json", 'rb').read())
    ko, kn = set(o) - {'animation_url', 'image'}, set(n) - {'animation_url', 'image'}
    if ko != kn: bad.append((r['token_id'], f'key set differs: {sorted(ko ^ kn)}')); continue
    d = [k for k in ko if o[k] != n[k]]
    if d: bad.append((r['token_id'], f'non-media values differ: {d}')); continue
    if ('animation_url' in n) != ('animation_url' in o): bad.append((r['token_id'], 'animation_url added/removed')); continue
    if n.get('image') != r['new_image'] or n.get('animation_url', '') != r['new_animation_url']: bad.append((r['token_id'], 'media values ≠ plan.csv')); continue
    if go_json(o).encode() != raw: bad.append((r['token_id'], 'source bytes not reproduced by serializer — format drift')); continue
print(f'{len(rows)} rows, {len(bad)} failures'); [print(' ', b) for b in bad[:20]]
sys.exit(1 if bad else 0)
