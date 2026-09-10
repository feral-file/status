#!/usr/bin/env python3
"""Phase-2 Step 1a: size every CDN pin unit at the origin bucket.

Reads step 0's cdn_dirs.csv and, for each unit, lists the origin bucket
prefix (`aws s3 ls --recursive --summarize`) to get true object count and
bytes — a HEAD on the CDN only sees single objects, and software previews
are whole directories. Bare-file units (URL with no `<uuid>/<ts>/…` dir
shape) are sized with `head-object`.

The answer this produces before anything is mirrored: total GB to pin, and
whether prod-02's headroom holds (repo ~654 GB / StorageMax 900 GB as of
2026-09-01 — pass the current numbers, don't trust these).

Usage (operator: needs read access to the origin bucket):
  BUCKET=<origin-bucket> [AWS_PROFILE=…] python3 tools/ipfs-mirror/size-dirs.py \
      --dirs ops/cdn-retirement-phase2/step0/cdn_dirs.csv \
      --out ops/cdn-retirement-phase2/step1/dir_sizes.csv \
      [--repo-used-gb 654 --storage-max-gb 900] [--dry-run]

Resumable: units already in --out are skipped on rerun.
--dry-run prints the aws commands for the first three units and exits.
"""
import argparse, csv, os, re, subprocess, sys

ap = argparse.ArgumentParser()
ap.add_argument('--dirs', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--repo-used-gb', type=float)
ap.add_argument('--storage-max-gb', type=float)
ap.add_argument('--dry-run', action='store_true')
a = ap.parse_args()
BUCKET = os.environ.get('BUCKET') or sys.exit('BUCKET env required (origin bucket name, no s3:// prefix)')
CDN = 'https://cdn.feralfileassets.com/'

units = list(csv.DictReader(open(a.dirs)))
done = {}
if os.path.exists(a.out):
    for r in csv.DictReader(open(a.out)):
        done[r['dir_or_file']] = r
new_file = not os.path.exists(a.out)
os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)

def key_of(unit):
    if not unit.startswith(CDN):
        return None  # non-CDN host (should not appear; handle manually)
    return unit[len(CDN):]

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=600)

if a.dry_run:
    for u in units[:3]:
        k = key_of(u['dir_or_file'])
        if u['dir_or_file'].endswith('/'):
            print(f"aws s3 ls --recursive --summarize 's3://{BUCKET}/{k}'")
        else:
            print(f"aws s3api head-object --bucket '{BUCKET}' --key '{k}'")
    sys.exit(0)

out_f = open(a.out, 'a', newline='')
w = csv.writer(out_f)
if new_file:
    w.writerow(['dir_or_file', 's3_prefix', 'n_objects', 'bytes', 'error'])

total_bytes = total_objs = 0
for i, u in enumerate(units, 1):
    unit = u['dir_or_file']
    if unit in done:
        d = done[unit]
        if not d['error']:
            total_bytes += int(d['bytes'] or 0); total_objs += int(d['n_objects'] or 0)
        continue
    k = key_of(unit)
    n = b = 0; err = ''
    if k is None:
        err = 'non-CDN host — size manually'
    elif unit.endswith('/'):
        r = run(['aws', 's3', 'ls', '--recursive', '--summarize', f's3://{BUCKET}/{k}'])
        if r.returncode != 0:
            err = r.stderr.strip()[:200]
        else:
            mo = re.search(r'Total Objects:\s*(\d+)', r.stdout)
            mb = re.search(r'Total Size:\s*(\d+)', r.stdout)
            n, b = int(mo.group(1)) if mo else 0, int(mb.group(1)) if mb else 0
            if n == 0:
                err = 'EMPTY prefix at origin — bytes may exist only on the CDN edge/nowhere'
    else:
        r = run(['aws', 's3api', 'head-object', '--bucket', BUCKET, '--key', k])
        if r.returncode != 0:
            err = 'head-object failed (missing at origin?): ' + r.stderr.strip()[:150]
        else:
            import json as _json
            n, b = 1, int(_json.loads(r.stdout).get('ContentLength', 0))
    w.writerow([unit, k or '', n, b, err]); out_f.flush()
    total_bytes += b; total_objs += n
    status = err or f'{n} objs, {b/1e9:.2f} GB'
    print(f'[{i}/{len(units)}] {status}  {unit}')
out_f.close()

gb = total_bytes / 1e9
print(f'\nTOTAL: {total_objs} objects, {gb:.1f} GB across {len(units)} units')
if a.repo_used_gb and a.storage_max_gb:
    after = a.repo_used_gb + gb
    print(f'prod-02 projection: {a.repo_used_gb:.0f} GB + {gb:.1f} GB = {after:.1f} GB '
          f'of StorageMax {a.storage_max_gb:.0f} GB ({after / a.storage_max_gb:.0%})')
    if after > 0.9 * a.storage_max_gb:
        print('WARNING: projected usage above 90% of StorageMax — settle capacity before mirroring')
errors = sum(1 for u in units if (done.get(u['dir_or_file'], {}).get('error') or '') != '')
print(f're-run to fill any errored units; record: {a.out}')
