#!/usr/bin/env python3
"""Enumerate every token of a contract straight from the chain.

The census and the DB exports only know exhibitions the API lists; hidden
exhibitions (mementos, partner drops) and manually deployed contracts never
reach them (2026-10-05: 6,023 CDN-dependent tokens sat on hidden exhibitions
outside every census). This builds the token list from the contract itself,
so `tools/metadata-regen/audit.py` (ETH) and `tezos-doc-regen.py` (Tezos)
have an input that cannot miss a token.

  RPC_URL=https://mainnet.infura.io/v3/<key> python3 tools/contract-audit/enumerate-tokens.py \
      0x7E6c132B8cb00899d17750E0fD982EA122C6b0f2 KT1CPeE8YGVG16xkpoE9sviUYoEzS7hWfu39 --out tokens.csv

Ethereum (0x…): ERC721Enumerable — totalSupply(), tokenByIndex(i), tokenURI(id),
read through Multicall3 so a contract costs a handful of eth_calls instead of
two per token (Infura bills per call; 2,000+ single calls rate-limit for
hours). RPC_URL is only needed when an 0x… contract is given.
Tezos (KT1…): the FA2 `token_metadata` big map via TzKT; token_uri is the
decoded `token_info[""]`.

Output csv: contract,token_id,token_uri — one row per token, the count is
checked against totalSupply / the big map's active key count (exit 1 on any
mismatch, duplicate or unreadable row).
"""
import argparse, csv, json, os, sys, time, urllib.request

MULTICALL3 = '0xcA11bde05977b3631167028862bE2a173976CA11'
SEL_TRY_AGGREGATE = 'bce38bd7'          # tryAggregate(bool,(address,bytes)[])
SEL_TOTAL_SUPPLY, SEL_TOKEN_BY_INDEX, SEL_TOKEN_URI = '18160ddd', '4f6ccce7', 'c87b56dd'
TZKT = 'https://api.tzkt.io/v1'

ap = argparse.ArgumentParser()
ap.add_argument('contracts', nargs='+', help='0x… (Ethereum) and/or KT1… (Tezos) addresses')
ap.add_argument('--out', default='tokens.csv')
ap.add_argument('--chunk', type=int, default=100, help='sub-calls per Multicall3 eth_call')
a = ap.parse_args()

def http_json(url, body=None):
    last = None
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, json.dumps(body).encode() if body is not None else None,
                                         {'Content-Type': 'application/json', 'User-Agent': 'contract-audit/enumerate-tokens'})
            return json.load(urllib.request.urlopen(req, timeout=120))
        except Exception as e:
            last = e
            time.sleep(2 ** attempt)
    sys.exit(f'request failed after retries: {type(last).__name__} {getattr(last, "code", "")}')

def eth_call(to, data):
    rpc = os.environ.get('RPC_URL') or sys.exit('RPC_URL is required for 0x… contracts')
    for attempt in range(8):
        r = http_json(rpc, {'jsonrpc': '2.0', 'id': 1, 'method': 'eth_call', 'params': [{'to': to, 'data': '0x' + data}, 'latest']})
        if 'result' in r:
            return bytes.fromhex(r['result'][2:])
        time.sleep(2 + 2 * attempt)      # rate limit / transient error object
    sys.exit(f'eth_call failed: {json.dumps(r.get("error"))[:200]}')

word = lambda n: n.to_bytes(32, 'big')
uint = lambda b, o: int.from_bytes(b[o:o + 32], 'big')

def multicall(target, calldatas):
    """tryAggregate(false, [(target, cd)…]) → list of return bytes (None where the sub-call reverted)."""
    t = bytes(12) + bytes.fromhex(target[2:])
    tuples = []
    for cd in calldatas:
        padded = cd + bytes(-len(cd) % 32)
        tuples.append(t + word(0x40) + word(len(cd)) + padded)
    offs, pos = [], 32 * len(tuples)
    for tp in tuples:
        offs.append(word(pos)); pos += len(tp)
    data = bytes.fromhex(SEL_TRY_AGGREGATE) + word(0) + word(0x40) + word(len(tuples)) + b''.join(offs) + b''.join(tuples)
    ret = eth_call(MULTICALL3, data.hex())
    base = uint(ret, 0); n = uint(ret, base)
    if n != len(calldatas):
        sys.exit(f'multicall returned {n} results for {len(calldatas)} calls')
    out, start = [], base + 32
    for i in range(n):
        o = start + uint(ret, start + 32 * i)
        success, boff = uint(ret, o), uint(ret, o + 32)
        ln = uint(ret, o + boff)
        out.append(ret[o + boff + 32:o + boff + 32 + ln] if success else None)
    return out

def abi_string(b):
    off = uint(b, 0); ln = uint(b, off)
    return b[off + 32:off + 32 + ln].decode()

def enumerate_eth(c):
    n = uint(eth_call(c, SEL_TOTAL_SUPPLY), 0)
    rows = []
    for i in range(0, n, a.chunk):
        idx = range(i, min(i + a.chunk, n))
        ids = multicall(c, [bytes.fromhex(SEL_TOKEN_BY_INDEX) + word(k) for k in idx])
        if any(x is None for x in ids):
            sys.exit(f'{c}: tokenByIndex reverted inside [{i}, {i + a.chunk}) — not ERC721Enumerable?')
        ids = [uint(x, 0) for x in ids]
        uris = multicall(c, [bytes.fromhex(SEL_TOKEN_URI) + word(t) for t in ids])
        for t, u in zip(ids, uris):
            rows.append((c.lower(), str(t), abi_string(u) if u else 'ERR:tokenURI reverted'))
        print(f'  {c[:10]}… {len(rows)}/{n}', file=sys.stderr, end='\r')
        time.sleep(0.5)
    print(file=sys.stderr)
    return rows, n

def enumerate_tezos(c):
    n = http_json(f'{TZKT}/contracts/{c}/bigmaps/assets.token_metadata')['activeKeys']
    rows, off = [], 0
    while True:
        page = http_json(f'{TZKT}/contracts/{c}/bigmaps/assets.token_metadata/keys?active=true&limit=1000&offset={off}&select=key,value')
        for r in page:
            info = r['value']['token_info']
            uri = bytes.fromhex(info['']).decode() if set(info) == {''} else f'ERR:token_info keys {sorted(info)}'
            rows.append((c, r['key'], uri))
        off += len(page)
        if len(page) < 1000:
            break
    return rows, n

all_rows, bad = [], 0
for c in a.contracts:
    rows, n = enumerate_eth(c) if c.startswith('0x') else enumerate_tezos(c)
    errs = sum(1 for r in rows if r[2].startswith('ERR:'))
    dup = len(rows) - len({r[1] for r in rows})
    flag = '' if len(rows) == n and not errs and not dup else '  ← MISMATCH'
    print(f'{c}: {len(rows)} tokens (chain says {n}), {errs} unreadable, {dup} duplicate{flag}', file=sys.stderr)
    bad += bool(flag)
    all_rows += rows
with open(a.out, 'w', newline='') as f:
    w = csv.writer(f, lineterminator='\n'); w.writerow(['contract', 'token_id', 'token_uri']); w.writerows(all_rows)
print(f'{len(all_rows)} rows → {a.out}', file=sys.stderr)
sys.exit(1 if bad else 0)
