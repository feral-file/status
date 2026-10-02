#!/usr/bin/env python3
"""Witness check: what each reader says one address holds, and what the chain says.

One run, one address, one block. Two readers are asked for the address's
holdings (Ethereum: the Feral File indexer and Blockscout; Tezos: TzKT and
objkt; all public, no key). Their lists are compared per token standard. Then
the chain itself is asked, at one pinned block, about (a) a seeded random
sample from each reader's list and (b) every token the two readers disagree
on. Ethereum: `ownerOf(tokenId)` for ERC-721, `balanceOf(address, tokenId)`
for ERC-1155, by eth_call. Tezos: the contract's own `%ledger` big map, read
from a node at the pinned block (key `(address, token_id)` -> balance, or
`token_id` -> owner). The result is one JSON entry a second party can
reproduce from this file, sign with their own key (tools/witness/sign.mjs),
and anyone can verify (tools/witness/verify.mjs).

    python3 tools/witness/witness.py --address 0x830cc132dd66F6491cEAA20206f398247143d9CF
    python3 tools/witness/witness.py --address tz1gMfctX4hBNpkUoE7RcYPBhNc1hpHddqh4

Writes two files to data/witness/:
  holdings_<chain>_<address>_<utc>.json        the entry (sign this)
  holdings_<chain>_<address>_<utc>.lists.json  both readers' full lists, referenced
                                               from the entry by sha256

Stdlib only, Python >= 3.11.
"""

import argparse
import hashlib
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "feral-file/witness-holdings/0.1"
UA = "feral-file-witness/0.1 (+https://witness.feralfile.com)"
INDEXER_URL = "https://indexer-v2.feralfile.com/graphql"
BLOCKSCOUT_URL = "https://eth.blockscout.com/api/v2"
RPC_URLS = ["https://ethereum-rpc.publicnode.com", "https://eth-mainnet.public.blastapi.io"]
TZKT_URL = "https://api.tzkt.io/v1"
OBJKT_URL = "https://data.objkt.com/v3/graphql"
TEZOS_RPC_URLS = ["https://rpc.tzbeta.net", "https://prod.tcinfra.net/rpc/mainnet"]
TEZOS_CHAIN = "tezos:NetXdQprcVkpaWU"  # CAIP-2 for Tezos mainnet
ETH_CHAIN = "eip155:1"
RPC_BATCH = 40
SEL_OWNER_OF = "6352211e"  # ownerOf(uint256)
SEL_BALANCE_OF = "00fdd58e"  # balanceOf(address,uint256)

INDEXER_QUERY = """query($o:[String!],$l:Uint8,$off:Uint64){
  tokens(owners:$o, limit:$l, offset:$off, include_unviewable:true, include_moderated:true){
    items{ token_cid standard contract_address token_number current_owner burned viewable moderation_status }
  }
}"""


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_json(url, body=None, tries=5):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, headers={"User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json"}
    )
    last = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  retry {attempt + 1}/{tries} {url.split('?')[0]}: {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    raise SystemExit(f"gave up on {url}: {last}")


def key(contract, token_id):
    return f"{contract.lower()}:{token_id}"


# ------------------------------------------------------------------ readers
#
# Each reader returns {"meta": {...}, "tokens": [ {contract, token_id, standard, ...} ]}.
# `standard` is "erc721" or "erc1155". Anything reader-specific stays under
# "reader_fields" so the comparison code reads one shape.


def read_indexer(address):
    fetched_at = utcnow()
    tokens, off, lim = [], 0, 100
    while True:
        d = http_json(INDEXER_URL, {"query": INDEXER_QUERY, "variables": {"o": [address], "l": lim, "off": str(off)}})
        if "errors" in d:
            raise SystemExit(f"indexer errors: {d['errors']}")
        page = d["data"]["tokens"]["items"]
        for t in page:
            tokens.append(
                {
                    "contract": t["contract_address"],
                    "token_id": t["token_number"],
                    "standard": t["standard"],
                    "reader_fields": {
                        "token_cid": t["token_cid"],
                        "current_owner": t["current_owner"],
                        "burned": t["burned"],
                        "viewable": t["viewable"],
                        "moderation_status": t["moderation_status"],
                    },
                }
            )
        print(f"  indexer offset {off}: {len(page)} (total {len(tokens)})", file=sys.stderr)
        if len(page) < lim:
            break
        off += lim
        time.sleep(0.3)
    return {
        "name": "feralfile-indexer",
        "operator": "Feral File",
        "endpoint": INDEXER_URL,
        "query": "tokens(owners:[address], include_unviewable:true, include_moderated:true), paged by 100",
        "fetched_at": fetched_at,
        "notes": "ERC-1155 rows carry no current_owner in this API; the address is the query, not a field.",
    }, tokens


def read_blockscout(address):
    fetched_at = utcnow()
    tokens = []
    for std, label in (("erc721", "ERC-721"), ("erc1155", "ERC-1155")):
        params = {"type": label}
        pages = 0
        while True:
            d = http_json(f"{BLOCKSCOUT_URL}/addresses/{address}/nft?" + urllib.parse.urlencode(params))
            pages += 1
            for it in d.get("items", []):
                tokens.append(
                    {
                        "contract": it["token"]["address_hash"],
                        "token_id": it["id"],
                        "standard": std,
                        "reader_fields": {"value": it.get("value"), "token_name": it["token"].get("name")},
                    }
                )
            nxt = d.get("next_page_params")
            print(f"  blockscout {label} page {pages}: total {len(tokens)}", file=sys.stderr)
            if not nxt:
                break
            params = {"type": label, **{k: str(v) for k, v in nxt.items()}}
            time.sleep(0.4)
    addr = http_json(f"{BLOCKSCOUT_URL}/addresses/{address}")
    return {
        "name": "blockscout",
        "operator": "Blockscout (public instance)",
        "endpoint": f"{BLOCKSCOUT_URL}/addresses/{{address}}/nft?type=ERC-721|ERC-1155",
        "query": "paged with next_page_params; a User-Agent header is required",
        "fetched_at": fetched_at,
        "notes": "Blockscout lists tokens it believes the address currently holds.",
    }, tokens, addr.get("ens_domain_name")


# -------------------------------------------------------------------- chain


def rpc_batch(url, calls, batch=RPC_BATCH):
    """Batched JSON-RPC. Providers cap batch sizes differently; on a failure the
    chunk is retried in halves down to single calls, so one strict provider
    cannot sink a run."""
    results = []
    for i in range(0, len(calls), batch):
        chunk = calls[i : i + batch]
        body = [{"jsonrpc": "2.0", "id": j, "method": m, "params": p} for j, (m, p) in enumerate(chunk)]
        try:
            out = http_json(url, body, tries=2)
            if not isinstance(out, list):
                raise ValueError(f"non-batch reply {str(out)[:120]}")
            by_id = {r["id"]: r for r in out}
            results += [by_id.get(j) for j in range(len(chunk))]
        except (SystemExit, ValueError) as e:
            if len(chunk) == 1:
                print(f"  rpc {url}: single call failed ({e}); recorded as no reply", file=sys.stderr)
                results.append(None)
            else:
                print(f"  rpc {url}: batch of {len(chunk)} failed; halving", file=sys.stderr)
                results += rpc_batch(url, chunk, max(1, len(chunk) // 2))
    return results


def pin_block(url):
    (blk,) = rpc_batch(url, [("eth_getBlockByNumber", ["latest", False])])
    r = blk["result"]
    return {
        "number": int(r["number"], 16),
        "hash": r["hash"],
        "timestamp": datetime.fromtimestamp(int(r["timestamp"], 16), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def calldata(token, address):
    tid = int(token["token_id"]).to_bytes(32, "big").hex()
    if token["standard"] == "erc721":
        return "0x" + SEL_OWNER_OF + tid
    return "0x" + SEL_BALANCE_OF + address[2:].lower().rjust(64, "0") + tid


def is_revert(err):
    """JSON-RPC error 3 is EVM execution reverted (EIP-1474); providers also
    spell it out. A revert is the contract answering "no such token"."""
    return err.get("code") == 3 or "revert" in str(err.get("message", "")).lower()


def is_evm_error(err):
    """The call ran and the EVM faulted (invalid opcode, out of gas): typically a
    contract that does not implement the selector at all, such as CryptoPunks,
    which has no ownerOf. The chain answered; it just cannot be asked this way."""
    m = str(err.get("message", "")).lower()
    return err.get("code") == -32003 or "evm error" in m or "invalid opcode" in m or "out of gas" in m


def chain_check(url, block_number, address, tokens, retries=4, batch=RPC_BATCH, pause=0.2):
    """For each token: does the chain say `address` holds it at `block_number`?
    Rows that got no chain answer (provider errors, rate limits) are retried
    `retries` times with growing pauses and shrinking batches."""
    results = chain_check_once(url, block_number, address, tokens, batch, pause)
    for k in range(retries):
        todo = [i for i, r in enumerate(results) if r["chain"].get("no_reply")]
        if not todo:
            break
        batch = max(5, batch // 2)
        print(f"  chain: retrying {len(todo)} unanswered calls (batch {batch})", file=sys.stderr)
        time.sleep(5 * (k + 1))
        again = chain_check_once(url, block_number, address, [tokens[i] for i in todo], batch, pause * 4)
        for i, r in zip(todo, again):
            results[i] = r
    return results


def chain_check_once(url, block_number, address, tokens, batch=RPC_BATCH, pause=0.2):
    tag = hex(block_number)
    results = []
    for i in range(0, len(tokens), batch):
        chunk = tokens[i : i + batch]
        calls = [("eth_call", [{"to": t["contract"], "data": calldata(t, address)}, tag]) for t in chunk]
        replies = rpc_batch(url, calls, batch)
        for t, r in zip(chunk, replies):
            row = {"contract": t["contract"], "token_id": t["token_id"], "standard": t["standard"]}
            call = "ownerOf" if t["standard"] == "erc721" else "balanceOf"
            if r is not None and "error" in r and is_evm_error(r["error"]):
                row["chain"] = {"call": call, "unanswerable": True, "error": r["error"].get("message")}
                row["held"] = None
            elif r is None or ("error" in r and not is_revert(r["error"])):
                # No answer, or a provider-side error (rate limit, upstream): not a chain fact.
                row["chain"] = {"call": call, "no_reply": True, "error": (r or {}).get("error")}
                row["held"] = None
            elif "error" in r or not r.get("result") or r["result"] == "0x":
                row["chain"] = {"call": call, "reverted": True}
                row["held"] = False
            elif t["standard"] == "erc721":
                owner = "0x" + r["result"][-40:]
                row["chain"] = {"call": "ownerOf", "owner": owner}
                row["held"] = owner.lower() == address.lower()
            else:
                bal = int(r["result"], 16)
                row["chain"] = {"call": "balanceOf", "balance": str(bal)}
                row["held"] = bal > 0
            results.append(row)
        print(f"  chain {i + len(chunk)}/{len(tokens)}", file=sys.stderr)
        time.sleep(pause)
    return results


def tally(rows):
    held = sum(1 for r in rows if r["held"] is True)
    not_held = sum(1 for r in rows if r["held"] is False)
    reverted = sum(1 for r in rows if r["chain"].get("reverted"))
    unanswerable = sum(1 for r in rows if r["chain"].get("unanswerable"))
    no_reply = sum(1 for r in rows if r["chain"].get("no_reply"))
    return {"checked": len(rows), "held": held, "not_held": not_held, "of_which_reverted": reverted, "unanswerable": unanswerable, "no_reply": no_reply}


# --------------------------------------------------------------- tezos readers


def read_tzkt(address):
    fetched_at = utcnow()
    tokens, off, lim = [], 0, 10000
    while True:
        rows = http_json(
            f"{TZKT_URL}/tokens/balances?"
            + urllib.parse.urlencode(
                {"account": address, "balance.gt": 0, "limit": lim, "offset": off,
                 "select": "balance,token.contract.address,token.tokenId,token.standard,token.id"}
            )
        )
        for r in rows:
            tokens.append(
                {
                    "contract": r["token.contract.address"],
                    "token_id": str(r["token.tokenId"]),
                    "standard": r["token.standard"],
                    "reader_fields": {"balance": r["balance"], "tzkt_token_id": r["token.id"]},
                }
            )
        print(f"  tzkt offset {off}: {len(rows)} (total {len(tokens)})", file=sys.stderr)
        if len(rows) < lim:
            break
        off += lim
        time.sleep(0.3)
    return {
        "name": "tzkt",
        "operator": "Baking Bad (public TzKT instance)",
        "endpoint": f"{TZKT_URL}/tokens/balances?account={{address}}&balance.gt=0",
        "query": "paged by 10000 with offset",
        "fetched_at": fetched_at,
        "notes": "Lists FA2 and FA1.2 balances above zero.",
    }, tokens


def read_objkt(address):
    fetched_at = utcnow()
    tokens, off, lim = [], 0, 500
    q = (
        'query($a:String!,$l:Int!,$o:Int!){ token_holder(where:{holder_address:{_eq:$a}, quantity:{_gt:"0"}},'
        " limit:$l, offset:$o, order_by:{token_pk:asc}){ quantity token{ token_id fa_contract } } }"
    )
    while True:
        d = http_json(OBJKT_URL, {"query": q, "variables": {"a": address, "l": lim, "o": off}})
        if "errors" in d:
            raise SystemExit(f"objkt errors: {d['errors']}")
        rows = d["data"]["token_holder"]
        for r in rows:
            tokens.append(
                {
                    "contract": r["token"]["fa_contract"],
                    "token_id": str(r["token"]["token_id"]),
                    "standard": "fa2",
                    "reader_fields": {"quantity": str(r["quantity"])},
                }
            )
        print(f"  objkt offset {off}: {len(rows)} (total {len(tokens)})", file=sys.stderr)
        if len(rows) < lim:
            break
        off += lim
        time.sleep(0.3)
    return {
        "name": "objkt",
        "operator": "objkt.com (public GraphQL)",
        "endpoint": OBJKT_URL,
        "query": "token_holder(where:{holder_address, quantity>0}), paged by 500",
        "fetched_at": fetched_at,
        "notes": "objkt indexes FA2 tokens only; every row is reported as fa2.",
    }, tokens


def tezos_domain(address):
    d = http_json(f"{TZKT_URL}/domains?" + urllib.parse.urlencode({"address": address, "reverse": "true", "select": "name"}))
    return d[0] if d else None


# ------------------------------------------------------------------ tezos chain
#
# A node answers "does X hold T" from the contract's own storage: the %ledger
# big map. Nothing below depends on an indexer; TzKT is only ever a reader.

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(s):
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\0" * (len(s) - len(s.lstrip("1"))) + b


def b58encode(b):
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


def b58check_decode(s, prefix_len):
    raw = b58decode(s)
    payload, chk = raw[:-4], raw[-4:]
    if hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != chk:
        raise ValueError(f"bad base58check: {s}")
    return payload[prefix_len:]


def b58check_encode(prefix, payload):
    raw = prefix + payload
    return b58encode(raw + hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4])


TZ_PREFIX = {"tz1": b"\x00\x00", "tz2": b"\x00\x01", "tz3": b"\x00\x02", "tz4": b"\x00\x03"}
TZ_B58_PREFIX = {"tz1": b"\x06\xa1\x9f", "tz2": b"\x06\xa1\xa1", "tz3": b"\x06\xa1\xa4", "tz4": b"\x06\xa1\xa6", "KT1": b"\x02\x5a\x79"}


def address_to_bytes(a):
    """Michelson's packed form of an address."""
    h = b58check_decode(a, 3)
    if a[:3] in TZ_PREFIX:
        return TZ_PREFIX[a[:3]] + h
    if a.startswith("KT1"):
        return b"\x01" + h + b"\x00"
    raise ValueError(f"unsupported address {a}")


def bytes_to_address(b):
    if b[0] == 0 and b[1] in (0, 1, 2, 3):
        return b58check_encode(TZ_B58_PREFIX[["tz1", "tz2", "tz3", "tz4"][b[1]]], b[2:22])
    if b[0] == 1:
        return b58check_encode(TZ_B58_PREFIX["KT1"], b[1:21])
    raise ValueError(f"unsupported packed address {b.hex()}")


def zarith(n):
    """Micheline integer body for n >= 0 (sign bit clear)."""
    out = bytearray()
    byte = n & 0x3F
    n >>= 6
    if n:
        byte |= 0x80
    out.append(byte)
    while n:
        byte = n & 0x7F
        n >>= 7
        if n:
            byte |= 0x80
        out.append(byte)
    return bytes(out)


def micheline_int(n):
    return b"\x00" + zarith(n)


def micheline_bytes(b):
    return b"\x0a" + len(b).to_bytes(4, "big") + b


def micheline_pair(a, b):
    return b"\x07\x07" + a + b


def expr_hash(micheline):
    """Big-map key hash: blake2b-256 of the PACKed key, base58check 'expr'."""
    return b58check_encode(b"\x0d\x2c\x40\x1b", hashlib.blake2b(b"\x05" + micheline, digest_size=32).digest())


def find_big_maps(typ, val, out, path=""):
    """Walk a storage type and value together; collect every big map with its annot, pointer and types."""
    prim = typ.get("prim")
    annots = [x[1:] for x in typ.get("annots", []) if x.startswith("%")]
    name = annots[0] if annots else None
    here = path + ("." if path and name else "") + (name or "")
    if prim == "big_map":
        if isinstance(val, dict) and "int" in val:
            out.append({"path": here, "annot": name, "ptr": int(val["int"]), "key_type": typ["args"][0], "value_type": typ["args"][1]})
        return
    if prim == "pair":
        ts = typ["args"]
        t_left, t_right = ts[0], (ts[1] if len(ts) == 2 else {"prim": "pair", "args": ts[1:]})
        if isinstance(val, list):
            vs = val
        elif isinstance(val, dict) and val.get("prim") == "Pair":
            vs = val["args"]
        else:
            return
        if len(vs) < 2:
            return
        v_left, v_right = vs[0], (vs[1] if len(vs) == 2 else {"prim": "Pair", "args": vs[1:]})
        find_big_maps(t_left, v_left, out, here)
        find_big_maps(t_right, v_right, out, here)
        return
    if prim == "option" and isinstance(val, dict) and val.get("prim") == "Some":
        find_big_maps(typ["args"][0], val["args"][0], out, here)
        return
    if prim == "or" and isinstance(val, dict) and val.get("prim") in ("Left", "Right"):
        find_big_maps(typ["args"][0 if val["prim"] == "Left" else 1], val["args"][0], out, here)
        return


def leaf_prims(t):
    """The leaf prims of a (possibly nested) pair type, in order."""
    if t.get("prim") == "pair":
        return [p for x in t["args"] for p in leaf_prims(x)]
    return [t.get("prim")]


class TezosLedger:
    """Per-contract ledger locator with a cache; reads keys from a node at one block."""

    def __init__(self, rpc, block_hash):
        self.rpc = rpc
        self.block = block_hash
        self.cache = {}

    def locate(self, contract):
        if contract in self.cache:
            return self.cache[contract]
        try:
            script = http_json(f"{self.rpc}/chains/main/blocks/{self.block}/context/contracts/{contract}/script", tries=3)
        except SystemExit as e:
            self.cache[contract] = {"error": f"script fetch failed: {e}"}
            return self.cache[contract]
        storage_t = next((x for x in script["code"] if x.get("prim") == "storage"), None)
        found = []
        if storage_t:
            find_big_maps(storage_t["args"][0], script["storage"], found)
        ledger = next((b for b in found if b["annot"] == "ledger"), None) or next((b for b in found if b["path"].endswith("ledger")), None)
        if not ledger:
            self.cache[contract] = {"error": "no %ledger big map in storage"}
            return self.cache[contract]
        kp = leaf_prims(ledger["key_type"])
        vp = leaf_prims(ledger["value_type"])
        if ledger["key_type"].get("prim") == "pair" and sorted(kp) == ["address", "nat"] and vp == ["nat"]:
            layout = "multi_asset" if kp == ["address", "nat"] else "multi_asset_reversed"
        elif kp == ["nat"] and vp == ["address"]:
            layout = "nft"
        else:
            self.cache[contract] = {"error": f"unsupported ledger layout key={kp} value={vp}"}
            return self.cache[contract]
        self.cache[contract] = {"ptr": ledger["ptr"], "layout": layout}
        return self.cache[contract]

    def holds(self, address, contract, token_id):
        """Returns (held: bool|None, chain: dict)."""
        led = self.locate(contract)
        if "error" in led:
            return None, {"call": "ledger", "unanswerable": True, "error": led["error"]}
        tid = int(token_id)
        if led["layout"] == "multi_asset":
            key_bytes = micheline_pair(micheline_bytes(address_to_bytes(address)), micheline_int(tid))
        elif led["layout"] == "multi_asset_reversed":
            key_bytes = micheline_pair(micheline_int(tid), micheline_bytes(address_to_bytes(address)))
        else:
            key_bytes = micheline_int(tid)
        url = f"{self.rpc}/chains/main/blocks/{self.block}/context/big_maps/{led['ptr']}/{expr_hash(key_bytes)}"
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        last = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    v = json.load(r)
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    v = None  # no such key: balance zero / no owner
                    break
                last = e
                time.sleep(2 * (attempt + 1))
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(2 * (attempt + 1))
        else:
            return None, {"call": "ledger", "no_reply": True, "error": str(last), "big_map": led["ptr"]}
        base = {"call": "ledger", "big_map": led["ptr"], "layout": led["layout"]}
        if led["layout"] == "nft":
            if v is None:
                return False, {**base, "owner": None}
            owner = v.get("string") or (bytes_to_address(bytes.fromhex(v["bytes"])) if "bytes" in v else None)
            return (owner == address), {**base, "owner": owner}
        bal = 0 if v is None else int(v.get("int", "0"))
        return bal > 0, {**base, "balance": str(bal)}


def tezos_pin_block(rpc):
    h = http_json(f"{rpc}/chains/main/blocks/head/header")
    return {"number": h["level"], "hash": h["hash"], "timestamp": h["timestamp"].replace("+00:00", "Z")}


def tezos_chain_check(rpc, block_hash, address, tokens, pause=0.1, retries=3):
    ledger = TezosLedger(rpc, block_hash)
    results = []
    for i, t in enumerate(tokens, 1):
        row = {"contract": t["contract"], "token_id": t["token_id"], "standard": t["standard"]}
        if t["standard"] != "fa2":
            row["chain"] = {"call": "ledger", "unanswerable": True, "error": f"{t['standard']} not checked (FA2 ledgers only)"}
            row["held"] = None
        else:
            held, chain = ledger.holds(address, t["contract"], t["token_id"])
            row["chain"], row["held"] = chain, held
        results.append(row)
        if i % 25 == 0 or i == len(tokens):
            print(f"  chain {i}/{len(tokens)}", file=sys.stderr)
        time.sleep(pause)
    for k in range(retries):
        todo = [i for i, r in enumerate(results) if r["chain"].get("no_reply")]
        if not todo:
            break
        print(f"  chain: retrying {len(todo)} unanswered reads", file=sys.stderr)
        time.sleep(5 * (k + 1))
        for i in todo:
            t = tokens[i]
            held, chain = ledger.holds(address, t["contract"], t["token_id"])
            results[i]["chain"], results[i]["held"] = chain, held
            time.sleep(pause * 2)
    return results


# --------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--address", required=True, help="Ethereum address (0x…)")
    ap.add_argument("--sample", type=int, default=120, help="tokens sampled per reader for the chain check")
    ap.add_argument("--seed", type=int, help="random seed for the sample (default: the pinned block number)")
    ap.add_argument("--rpc", action="append", help="JSON-RPC URL; repeatable; first is primary, the rest re-check disagreements")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "data" / "witness"))
    a = ap.parse_args()
    address = a.address
    tezos = address.startswith(("tz", "KT1"))
    chain_id = TEZOS_CHAIN if tezos else ETH_CHAIN
    rpcs = a.rpc or (TEZOS_RPC_URLS if tezos else RPC_URLS)

    if tezos:
        print("reader: tzkt", file=sys.stderr)
        ix_meta, ix_tokens = read_tzkt(address)
        print("reader: objkt", file=sys.stderr)
        bs_meta, bs_tokens = read_objkt(address)
        name, name_system, name_source = tezos_domain(address), "tezos-domains", f"{TZKT_URL}/domains?address={{address}}&reverse=true"
        block = tezos_pin_block(rpcs[0])
        standards = ("fa2", "fa1.2")

        def check(url, toks, **kw):
            return tezos_chain_check(url, block["hash"], address, toks)
    else:
        print("reader: feralfile-indexer", file=sys.stderr)
        ix_meta, ix_tokens = read_indexer(address)
        print("reader: blockscout", file=sys.stderr)
        bs_meta, bs_tokens, name = read_blockscout(address)
        name_system, name_source = "ens", "blockscout /addresses/{address} ens_domain_name"
        block = pin_block(rpcs[0])
        standards = ("erc721", "erc1155")

        def check(url, toks, **kw):
            return chain_check(url, block["number"], address, toks, **kw)
    reader_a, reader_b = ix_meta["name"], bs_meta["name"]

    seed = a.seed if a.seed is not None else block["number"]
    print(f"block {block['number']} seed {seed}", file=sys.stderr)

    readers = []
    for meta, toks in ((ix_meta, ix_tokens), (bs_meta, bs_tokens)):
        keys = sorted(key(t["contract"], t["token_id"]) + ":" + t["standard"] for t in toks)
        meta = dict(meta)
        meta["count"] = {"total": len(toks), **{std: sum(1 for t in toks if t["standard"] == std) for std in standards}}
        meta["list_sha256"] = hashlib.sha256("\n".join(keys).encode()).hexdigest()
        readers.append(meta)

    # Comparison, per standard, keyed contract:token_id.
    by = {}
    for rname, toks in ((reader_a, ix_tokens), (reader_b, bs_tokens)):
        for std in standards:
            by[(rname, std)] = {key(t["contract"], t["token_id"]): t for t in toks if t["standard"] == std}
    comparison = []
    diff_tokens = []  # (only_in, not_in, token)
    for std in standards:
        A, B = by[(reader_a, std)], by[(reader_b, std)]
        only_a = sorted(set(A) - set(B))
        only_b = sorted(set(B) - set(A))
        comparison.append(
            {
                "standard": std,
                "both": len(set(A) & set(B)),
                f"only_{reader_a}": len(only_a),
                f"only_{reader_b}": len(only_b),
            }
        )
        diff_tokens += [(reader_a, reader_b, A[k]) for k in only_a]
        diff_tokens += [(reader_b, reader_a, B[k]) for k in only_b]

    # Chain check: a seeded sample per reader, then every disagreement.
    rng = random.Random(seed)
    samples = []
    for rname, toks in ((reader_a, ix_tokens), (reader_b, bs_tokens)):
        pick = rng.sample(toks, min(a.sample, len(toks)))
        print(f"chain: sample of {len(pick)} from {rname}", file=sys.stderr)
        rows = check(rpcs[0], pick)
        samples.append({"reader": rname, "seed": seed, **tally(rows), "tokens": rows})

    print(f"chain: {len(diff_tokens)} disagreements", file=sys.stderr)
    diff_rows = check(rpcs[0], [t for _, _, t in diff_tokens])
    for (only_in, not_in, _), row in zip(diff_tokens, diff_rows):
        row["listed_by"] = only_in
        row["missing_from"] = not_in
    differences = []
    for std in standards:
        for only_in, not_in in ((reader_a, reader_b), (reader_b, reader_a)):
            rows = [r for r in diff_rows if r["standard"] == std and r["listed_by"] == only_in]
            if rows:
                differences.append({"standard": std, "listed_by": only_in, "missing_from": not_in, **tally(rows), "tokens": rows})

    # Second opinion on the chain itself: every "not held" verdict re-read on another RPC.
    recheck = None
    if len(rpcs) > 1:
        suspects = [r for r in diff_rows + [t for s in samples for t in s["tokens"]] if r["held"] is False]
        print(f"chain: re-reading {len(suspects)} not-held verdicts on {rpcs[1]}", file=sys.stderr)
        again = check(rpcs[1], suspects, batch=10, pause=1.0)
        disagree = [
            {"contract": x["contract"], "token_id": x["token_id"], "primary": x["chain"], "secondary": y["chain"]}
            for x, y in zip(suspects, again)
            if y["held"] is not None and x["held"] != y["held"]
        ]
        unanswered = sum(1 for y in again if y["held"] is None)
        recheck = {
            "rpc": rpcs[1],
            "rechecked": len(suspects),
            "confirmed": len(suspects) - len(disagree) - unanswered,
            "secondary_unanswered": unanswered,
            "rpc_disagreements": disagree,
        }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"holdings_{chain_id.replace(':', '-')}_{address if tezos else address.lower()}_{stamp}"
    lists = {"schema": SCHEMA + "/lists", "address": address, "readers": {reader_a: ix_tokens, reader_b: bs_tokens}}
    lists_bytes = json.dumps(lists, separators=(",", ":"), sort_keys=True).encode()

    entry = {
        "schema": SCHEMA,
        "kind": "holdings",
        "subject": {
            "chain": chain_id,
            "address": address,
            "name": name,
            "name_system": name_system,
            "name_source": name_source,
            **({"ens": name, "ens_source": name_source} if not tezos else {}),
        },
        "observed_at": utcnow(),
        "chain_state": {"block": block["number"], "block_hash": block["hash"], "block_timestamp": block["timestamp"], "rpc": rpcs[0]},
        "readers": readers,
        "comparison": {"keyed_by": "contract:token_id, per standard", "pairs": comparison},
        "chain_check": {
            "method": (
                (
                    "Node RPC at chain_state.block_hash: the contract's %ledger big map, located from its own "
                    "storage type, read by key hash. Key (address, token_id) -> balance > 0, or key token_id -> "
                    "owner == address. A missing key is not held. A contract whose ledger cannot be located or "
                    "whose layout is not one of those two is recorded as unanswerable; FA1.2 tokens are not checked. "
                    "Reader lists were fetched shortly before the block was pinned (see readers[].fetched_at); "
                    "a transfer in that window shows up as a disagreement."
                )
                if tezos
                else (
                    "eth_call at chain_state.block: ownerOf(tokenId) == address for ERC-721; "
                    "balanceOf(address, tokenId) > 0 for ERC-1155. A revert counts as not held; a contract that "
                    "faults on the call (no such selector, e.g. CryptoPunks) is recorded as unanswerable. "
                    "Reader lists were fetched shortly before the block was pinned (see readers[].fetched_at); "
                    "a transfer in that window shows up as a disagreement."
                )
            ),
            "sample_size": a.sample,
            "samples": samples,
            "differences": differences,
            "rpc_recheck": recheck,
        },
        "lists": {"file": base + ".lists.json", "sha256": hashlib.sha256(lists_bytes).hexdigest()},
        "produced_by": {"tool": "tools/witness/witness.py", "repo": "https://github.com/feral-file/status", "schema_doc": "tools/witness/README.md"},
    }

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / (base + ".lists.json")).write_bytes(lists_bytes)
    (out / (base + ".json")).write_text(json.dumps(entry, indent=1) + "\n")
    print(json.dumps({"entry": str(out / (base + ".json")), "block": block["number"], "readers": [{r["name"]: r["count"]} for r in readers], "comparison": comparison, "samples": [{s["reader"]: {k: s[k] for k in ("checked", "held", "not_held", "unanswerable", "no_reply")}} for s in samples], "differences": [{d["listed_by"] + "/" + d["standard"]: {k: d[k] for k in ("checked", "held", "not_held", "unanswerable", "no_reply")}} for d in differences], "rpc_recheck": (recheck or {}).get("rpc_disagreements")}, indent=1))


if __name__ == "__main__":
    main()
