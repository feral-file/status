#!/usr/bin/env python3
"""Live health scan of every non-IPFS media URL the census references.

Why this exists (2026-09-02): the census DOES probe CDN media and records
http_status per row, but nothing ever turned the failures into a fix list —
the 2026-09-01 census carried five `_unique-thumbnails/N-large.jpg` 403s
(I KNOW, exhibition 99aa32cb) that sat unnoticed in the published CSV until
a human hit one in a browser. This tool closes that gap: it re-probes every
distinct non-IPFS URL live (browser-shaped request), independent of the
census-time result, and emits the broken set with the affected tokens.

Population: rows of the given census CSV with hosting in {cdn, other} and
resource != metadata (metadata endpoints are fetched by every census run
itself — `Metadata errors` in the summary already covers them; pass
--include-metadata to scan them too).

Probe rule: GET with Range: bytes=0-1023, browser User-Agent, redirects
followed. ok = HTTP 200/206. Retries ×3 with backoff on 429/5xx/network
errors so transient blips don't pollute the list (the census-rescan lesson).

Resumable: each URL's result is appended to --state (jsonl) as it lands;
rerunning skips URLs already probed (pass --reprobe-failed to retry the
recorded failures instead of trusting them).

Usage:
  python3 tools/nonipfs-scan/scan.py \
      --census data/census/token_census_20260901T093949Z.csv \
      --state  ops/nonipfs-scan/state_<date>.jsonl \
      --out    ops/nonipfs-scan/results_<date>.csv

Output: --out CSV (one row per distinct URL: status, ok, tokens affected),
a FAILURES section on stdout grouped by directory, and exit code 1 if any
URL is broken (cron-friendly). Run data goes to ops/, logic stays here.
"""
import argparse, csv, json, os, sys, threading, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import requests

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36')
RETRY_STATUSES = {429, 500, 502, 503, 504}
ATTEMPTS = 3
BACKOFF = 4  # seconds, ×attempt

ap = argparse.ArgumentParser()
ap.add_argument('--census', required=True, help='census CSV to take the URL population from')
ap.add_argument('--state', required=True, help='jsonl of probe results; append-only, resume by rerunning')
ap.add_argument('--out', required=True, help='results CSV (all URLs, ok and broken)')
ap.add_argument('--include-metadata', action='store_true', help='also scan resource=metadata endpoint URLs')
ap.add_argument('--reprobe-failed', action='store_true', help='re-probe URLs whose stored result is a failure')
ap.add_argument('--workers', type=int, default=12)
ap.add_argument('--timeout', type=float, default=30)
a = ap.parse_args()

# --- population: distinct URL -> affected token rows -------------------------
tokens_by_url = defaultdict(list)
with open(a.census) as f:
    for r in csv.DictReader(f):
        if r['hosting'] not in ('cdn', 'other'):
            continue
        if r['resource'] == 'metadata' and not a.include_metadata:
            continue
        tokens_by_url[r['url']].append(r)
urls = sorted(tokens_by_url)
print(f'{len(urls)} distinct non-IPFS URLs from {a.census}', flush=True)

# --- resume state ------------------------------------------------------------
done = {}
if os.path.exists(a.state):
    with open(a.state) as f:
        for line in f:
            rec = json.loads(line)
            done[rec['url']] = rec  # latest wins
pend = [u for u in urls if u not in done or (a.reprobe_failed and not done[u]['ok'])]
print(f'{len(done)} in state; {len(pend)} to probe', flush=True)

# --- probe -------------------------------------------------------------------
os.makedirs(os.path.dirname(a.state) or '.', exist_ok=True)
state_lock = threading.Lock()
state_f = open(a.state, 'a')
counter = {'n': 0, 'fail': 0}
local = threading.local()

def session():
    if not hasattr(local, 's'):
        local.s = requests.Session()
        local.s.headers.update({'User-Agent': UA, 'Accept': '*/*'})
    return local.s

def probe(url):
    last = {}
    for attempt in range(1, ATTEMPTS + 1):
        try:
            resp = session().get(url, headers={'Range': 'bytes=0-1023'},
                                 timeout=a.timeout, allow_redirects=True, stream=True)
            body = resp.raw.read(1024, decode_content=True) if resp.status_code in (200, 206) else b''
            last = {'status': resp.status_code,
                    'content_type': resp.headers.get('Content-Type', ''),
                    'error': ''}
            resp.close()
            if resp.status_code in (200, 206) and len(body) > 0:
                last['ok'] = True
                break
            last['ok'] = False
            if resp.status_code in (200, 206):
                last['error'] = 'empty body'
            if resp.status_code not in RETRY_STATUSES:
                break
        except requests.RequestException as e:
            last = {'status': 0, 'content_type': '', 'ok': False,
                    'error': type(e).__name__ + ': ' + str(e)[:120]}
        if attempt < ATTEMPTS:
            time.sleep(BACKOFF * attempt)
    last.update({'url': url, 'attempts': attempt})
    with state_lock:
        state_f.write(json.dumps(last) + '\n')
        state_f.flush()
        done[url] = last
        counter['n'] += 1
        if not last['ok']:
            counter['fail'] += 1
            print(f"[{counter['n']}/{len(pend)}] FAIL {last['status'] or last['error']} {url}", flush=True)
        elif counter['n'] % 500 == 0:
            print(f"[{counter['n']}/{len(pend)}] ok (progress), {counter['fail']} failures so far", flush=True)

with ThreadPoolExecutor(max_workers=a.workers) as ex:
    list(ex.map(probe, pend))
state_f.close()

missing = [u for u in urls if u not in done]
if missing:
    sys.exit(f'{len(missing)} URLs still unprobed - rerun to continue')

# --- report ------------------------------------------------------------------
os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
with open(a.out, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['url', 'host', 'ok', 'status', 'content_type', 'attempts', 'error',
                'n_token_rows', 'resources', 'exhibitions', 'example_contract', 'example_token_id'])
    for u in urls:
        d, rows = done[u], tokens_by_url[u]
        w.writerow([u, urlsplit(u).netloc, d['ok'], d['status'], d['content_type'],
                    d['attempts'], d['error'], len(rows),
                    ';'.join(sorted({r['resource'] for r in rows})),
                    ';'.join(sorted({r['exhibition'] for r in rows})),
                    rows[0]['contract'], rows[0]['token_id']])

broken = [u for u in urls if not done[u]['ok']]
print(f'\nSCAN DONE: {len(urls)} URLs, {len(broken)} broken, results in {a.out}', flush=True)
if broken:
    by_dir = defaultdict(list)
    for u in broken:
        by_dir[u.rsplit('/', 1)[0] + '/'].append(u)
    print('\nFAILURES by directory:')
    for d in sorted(by_dir):
        us = by_dir[d]
        toks = {(r['contract'], r['token_id']) for u in us for r in tokens_by_url[u]}
        exhs = {r['exhibition'] for u in us for r in tokens_by_url[u]}
        print(f'  {d}\n    {len(us)} URLs, {len(toks)} tokens, exhibitions: {", ".join(sorted(exhs))}')
        for u in sorted(us)[:10]:
            print(f'    {done[u]["status"] or done[u]["error"]}  {u}')
        if len(us) > 10:
            print(f'    ... and {len(us) - 10} more')
    sys.exit(1)
