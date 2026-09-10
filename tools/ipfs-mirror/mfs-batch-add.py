#!/usr/bin/env python3
"""Batched, resumable upload of a local directory into kubo MFS.

Called by mirror-add-pin.sh for directory units. Exists because the per-file
loop was latency-bound: 2 curl round-trips × ~0.3 s over the tunnel × 45k
files ≈ 8 h for crystalline. This batches many files per POST
(`/api/v0/add?to-files=<mfs dir>/` places each multipart part by its
filename — verified live 2026-09-03), turning 45k round-trips into ~a few
hundred, so wall-clock is transfer-bound again.

- Groups files by parent directory; one `files/ls` per directory gives the
  resume state (already-present names are skipped) — no per-file stat.
- Batches up to --batch-files (200) or --batch-bytes (256 MB), whichever
  first; a file larger than the cap ships alone.
- Prints progress per batch to stderr; prints the finished MFS directory's
  root hash (files/stat) as the LAST stdout line — the caller pins that.

Usage: mfs-batch-add.py <local-dir> <mfs-path> [--api http://127.0.0.1:5001]
"""
import argparse, json, os, sys, time, urllib.parse
import requests

ap = argparse.ArgumentParser()
ap.add_argument('local_dir')
ap.add_argument('mfs_path')
ap.add_argument('--api', default='http://127.0.0.1:5001')
ap.add_argument('--batch-files', type=int, default=200)
ap.add_argument('--batch-bytes', type=int, default=256 * 1024 * 1024)
a = ap.parse_args()
API = a.api.rstrip('/') + '/api/v0'
S = requests.Session()

def api(path, **params):
    r = S.post(f'{API}/{path}', params=params, timeout=300)
    r.raise_for_status()
    return r

# files grouped by parent dir (relative to local_dir)
by_dir = {}
total = 0
for base, _dirs, files in os.walk(a.local_dir):
    rel = os.path.relpath(base, a.local_dir)
    rel = '' if rel == '.' else rel
    if files:
        by_dir[rel] = sorted(files)
        total += len(files)
print(f'{total} files in {len(by_dir)} directories', file=sys.stderr)

done = 0
sent = 0
t0 = time.time()
for rel in sorted(by_dir):
    mfs_dir = a.mfs_path.rstrip('/') + ('/' + rel if rel else '')
    api('files/mkdir', arg=mfs_dir, parents='true', **{'cid-version': 0})
    try:
        r = api('files/ls', arg=mfs_dir)
        existing = {e['Name'] for e in (r.json().get('Entries') or [])}
    except requests.HTTPError:
        existing = set()
    pending = [f for f in by_dir[rel] if f not in existing]
    done += len(by_dir[rel]) - len(pending)
    batch, batch_bytes = [], 0
    def flush():
        global done, sent, batch, batch_bytes
        if not batch:
            return
        parts = [('file', (urllib.parse.quote(name, safe=''), open(path, 'rb')))
                 for name, path in batch]
        for attempt in range(3):
            try:
                r = S.post(f'{API}/add',
                           params={'quieter': 'true', 'cid-version': 0, 'hidden': 'true',
                                   'pin': 'false', 'to-files': mfs_dir + '/'},
                           files=parts, timeout=1800)
                r.raise_for_status()
                break
            except Exception as e:
                if attempt == 2:
                    print(f'FAILED batch in {mfs_dir} after 3 tries: {e}', file=sys.stderr)
                    sys.exit(1)
                time.sleep(10 * (attempt + 1))
                for _n, fh in parts:
                    fh[1].seek(0)
        for _n, fh in parts:
            fh[1].close()
        done += len(batch); sent += batch_bytes
        rate = sent / max(1, time.time() - t0) / 1e6
        print(f'  {done}/{total} files, {sent/1e9:.2f} GB sent, {rate:.1f} MB/s', file=sys.stderr)
        batch, batch_bytes = [], 0
    for f in pending:
        p = os.path.join(a.local_dir, rel, f) if rel else os.path.join(a.local_dir, f)
        sz = os.path.getsize(p)
        if batch and (len(batch) >= a.batch_files or batch_bytes + sz > a.batch_bytes):
            flush()
        batch.append((f, p)); batch_bytes += sz
    flush()

st = api('files/stat', arg=a.mfs_path).json()
print(f'MFS build complete: {st["CumulativeSize"]/1e9:.2f} GB', file=sys.stderr)
print(st['Hash'])
