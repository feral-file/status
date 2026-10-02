#!/usr/bin/env python3
"""Witness check: what each reader says one address holds, and what the chain says.

One run, one address, one block. Two readers are asked for the address's
holdings (the Feral File indexer and Blockscout; both public, no key). Their
lists are compared per token standard. Then the chain itself is asked, at one
pinned block, about (a) a seeded random sample from each reader's list and
(b) every token the two readers disagree on: `ownerOf(tokenId)` for ERC-721,
`balanceOf(address, tokenId)` for ERC-1155. The result is one JSON entry a
second party can reproduce from this file, and sign with their own key
(tools/witness/sign.mjs), and anyone can verify (tools/witness/verify.mjs).

    python3 tools/witness/witness.py --address 0x830cc132dd66F6491cEAA20206f398247143d9CF

Writes two files to data/witness/:
  holdings_<chain>_<address>_<utc>.json        the entry (sign this)
  holdings_<chain>_<address>_<utc>.lists.json  both readers' full lists, referenced
                                               from the entry by sha256

Stdlib only, Python >= 3.11. Ethereum mainnet only for now; the reader
functions are the place to add a chain.
"""

import argparse
import hashlib
import json
import random
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "feral-file/witness-holdings/0.1"
UA = "feral-file-witness/0.1 (+https://status.feralfile.com)"
CHAIN = "eip155:1"
INDEXER_URL = "https://indexer-v2.feralfile.com/graphql"
BLOCKSCOUT_URL = "https://eth.blockscout.com/api/v2"
RPC_URLS = ["https://ethereum-rpc.publicnode.com", "https://eth.drpc.org"]
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
    rpcs = a.rpc or RPC_URLS

    print("reader: feralfile-indexer", file=sys.stderr)
    ix_meta, ix_tokens = read_indexer(address)
    print("reader: blockscout", file=sys.stderr)
    bs_meta, bs_tokens, ens = read_blockscout(address)

    block = pin_block(rpcs[0])
    seed = a.seed if a.seed is not None else block["number"]
    print(f"block {block['number']} seed {seed}", file=sys.stderr)

    readers = []
    for meta, toks in ((ix_meta, ix_tokens), (bs_meta, bs_tokens)):
        keys = sorted(key(t["contract"], t["token_id"]) + ":" + t["standard"] for t in toks)
        meta = dict(meta)
        meta["count"] = {
            "total": len(toks),
            "erc721": sum(1 for t in toks if t["standard"] == "erc721"),
            "erc1155": sum(1 for t in toks if t["standard"] == "erc1155"),
        }
        meta["list_sha256"] = hashlib.sha256("\n".join(keys).encode()).hexdigest()
        readers.append(meta)

    # Comparison, per standard, keyed contract:token_id.
    by = {}
    for name, toks in (("feralfile-indexer", ix_tokens), ("blockscout", bs_tokens)):
        for std in ("erc721", "erc1155"):
            by[(name, std)] = {key(t["contract"], t["token_id"]): t for t in toks if t["standard"] == std}
    comparison = []
    diff_tokens = []  # (only_in, not_in, token)
    for std in ("erc721", "erc1155"):
        A, B = by[("feralfile-indexer", std)], by[("blockscout", std)]
        only_a = sorted(set(A) - set(B))
        only_b = sorted(set(B) - set(A))
        comparison.append(
            {
                "standard": std,
                "both": len(set(A) & set(B)),
                "only_feralfile-indexer": len(only_a),
                "only_blockscout": len(only_b),
            }
        )
        diff_tokens += [("feralfile-indexer", "blockscout", A[k]) for k in only_a]
        diff_tokens += [("blockscout", "feralfile-indexer", B[k]) for k in only_b]

    # Chain check: a seeded sample per reader, then every disagreement.
    rng = random.Random(seed)
    samples = []
    for name, toks in (("feralfile-indexer", ix_tokens), ("blockscout", bs_tokens)):
        pick = rng.sample(toks, min(a.sample, len(toks)))
        print(f"chain: sample of {len(pick)} from {name}", file=sys.stderr)
        rows = chain_check(rpcs[0], block["number"], address, pick)
        samples.append({"reader": name, "seed": seed, **tally(rows), "tokens": rows})

    print(f"chain: {len(diff_tokens)} disagreements", file=sys.stderr)
    diff_rows = chain_check(rpcs[0], block["number"], address, [t for _, _, t in diff_tokens])
    for (only_in, not_in, _), row in zip(diff_tokens, diff_rows):
        row["listed_by"] = only_in
        row["missing_from"] = not_in
    differences = []
    for std in ("erc721", "erc1155"):
        for only_in, not_in in (("feralfile-indexer", "blockscout"), ("blockscout", "feralfile-indexer")):
            rows = [r for r in diff_rows if r["standard"] == std and r["listed_by"] == only_in]
            if rows:
                differences.append({"standard": std, "listed_by": only_in, "missing_from": not_in, **tally(rows), "tokens": rows})

    # Second opinion on the chain itself: every "not held" verdict re-read on another RPC.
    recheck = None
    if len(rpcs) > 1:
        suspects = [r for r in diff_rows + [t for s in samples for t in s["tokens"]] if r["held"] is False]
        print(f"chain: re-reading {len(suspects)} not-held verdicts on {rpcs[1]}", file=sys.stderr)
        again = chain_check(rpcs[1], block["number"], address, suspects, batch=10, pause=1.0)
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
    base = f"holdings_{CHAIN.replace(':', '-')}_{address.lower()}_{stamp}"
    lists = {"schema": SCHEMA + "/lists", "address": address, "readers": {"feralfile-indexer": ix_tokens, "blockscout": bs_tokens}}
    lists_bytes = json.dumps(lists, separators=(",", ":"), sort_keys=True).encode()

    entry = {
        "schema": SCHEMA,
        "kind": "holdings",
        "subject": {"chain": CHAIN, "address": address, "ens": ens, "ens_source": "blockscout /addresses/{address} ens_domain_name"},
        "observed_at": utcnow(),
        "chain_state": {"block": block["number"], "block_hash": block["hash"], "block_timestamp": block["timestamp"], "rpc": rpcs[0]},
        "readers": readers,
        "comparison": {"keyed_by": "contract:token_id, per standard", "pairs": comparison},
        "chain_check": {
            "method": (
                "eth_call at chain_state.block: ownerOf(tokenId) == address for ERC-721; "
                "balanceOf(address, tokenId) > 0 for ERC-1155. A revert counts as not held; a contract that "
                "faults on the call (no such selector, e.g. CryptoPunks) is recorded as unanswerable. "
                "Reader lists were fetched shortly before the block was pinned (see readers[].fetched_at); "
                "a transfer in that window shows up as a disagreement."
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
