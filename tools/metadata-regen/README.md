# metadata-regen — move token metadata media from CDN to `ipfs://` (V2/V3/V4)

*(formerly `tools/v2-metadata-regen`; phase-2 added the V3/V4 tools below)*

Goal 2 of `ops/bitmark-cdn-retirement.md` (feral-file/feral-file#3435): every
already-swapped `FeralfileExhibitionV2` token whose **on-chain** metadata still
points `animation_url` / `image` at `cdn.feralfileassets.com` (or
`imagedelivery.net`) gets a new metadata directory whose media are `ipfs://`
CIDs, registered on-chain. Contract-agnostic; re-runnable; every step leaves a
csv record.

## What the contract does (verified from the Sourcify-verified source, 2026-08-28)

```solidity
function tokenURI(uint256 tokenId) … {
    string memory baseURI = _tokenBaseURI;            // "https://ipfs.bitmark.com/ipfs/" on all 17 contracts
    if (bytes(baseURI).length == 0) baseURI = "ipfs://";
    return string(abi.encodePacked(baseURI, artworkEditions[tokenId].ipfsCID, "/metadata.json"));
}
function updateArtworkEditionIPFSCid(uint256 tokenId, string memory ipfsCID) external onlyAuthorized {  // trustee || owner
    require(_exists(tokenId));
    require(!registeredIPFSCIDs[ipfsCID], "ipfs id has registered");   // one dir per token, never reuse a CID
    delete registeredIPFSCIDs[edition.ipfsCID]; registeredIPFSCIDs[ipfsCID] = true; edition.ipfsCID = ipfsCID;
}
```

The contract holds **only the directory CID**. `animation_url`, `image` and any
`?edition_number=…&blockchain=…` parameters are plain values inside
`metadata.json` — no contract logic reads or builds them. Changing a token's
media therefore means: new `metadata.json` → new directory CID → one
`updateArtworkEditionIPFSCid` tx. Nothing else on-chain changes (owner,
edition id, royalties untouched).

## Rewrite rule (= `swap.GenerateArtworkSwappingMetadata` in feral-file-server)

| series.medium | `animation_url` | `image` |
|---|---|---|
| video, audio, software, animated gif, 3d | preview `ipfs_reference.ipfs_uri` | thumbnail `ipfs_reference.ipfs_uri` |
| image | untouched | preview `ipfs_reference.ipfs_uri` |
| txt, pdf, unknown (server default) | untouched | thumbnail `ipfs_reference.ipfs_uri` |

Every other key is byte-preserved (server JSON shape: compact, sorted keys, Go
HTML escaping — verified byte-identical round trip). Guards in `gen.py`, each
sending the token to `blocked.csv` instead of writing a dir:

- the DB's `swaps.ipfs_cid` must equal the CID actually on chain;
- `swaps.token` may be decimal or (older swaps) the same uint256 as 64-hex — verified on chain to be the same token. Chain calls use decimal (`token_id`); SQL uses the DB's own string (`token_id_db`), carried through plan/result csv.
- `edition_index` in the fetched metadata must equal the DB edition;
- a needed reference must exist and be `ipfs://<cid>…` (never `ipfs://?…`);
- **parameters are preserved**: every query parameter on the old URL
  (`edition_number`, `blockchain`, …) must appear with the same value on the
  new `ipfs://` URI, and `edition_number` must equal the token's edition.
  Generative works read these at runtime; 87 CDN `animation_url`s carry them.

## Pipeline

```
audit.py ──► gen.py ──► check-dirs.py ──► verify-media.py ──► pin.sh ──► make-configs.py ──► update-token-uri (per contract) ──► gen-sql.py ──► census
 (chain)     (local)    (public gateways)  (prod-02)     (runs/<c>/)         preflight → --limit 1 → run-all → check      (DB)
```

### 0 · inputs

```bash
# DB export (read-only), from the server DB:
psql … -f ../../ops/3435-hls-fix/db/export-v2-cdn-tokens.sql     # → export.csv (contract,token_id,edition,old_metadata_cid,medium,preview_ipfs_uri,thumbnail_ipfs_uri,…)
```

### 1 · audit — build the fix list from the chain

```bash
RPC_URL=https://<paid rpc> python3 audit.py export.csv --db-export export.csv
#   → audit.csv (per token: onchain_cid, animation_url, image, classes, needs_fix, db_cid_match)
#   → audit.contracts.csv (trustee / owner / tokenBaseURI per contract)
```
Batched `eth_call`s paced at `--rps` calls/s (default 20; Infura bills `eth_call` at 80 credits — Developer 2,000 cps ≈ 25/s, Team 5,000 cps ≈ 62/s). 429 / `-32005` responses halve the rate and retry the batch, never land as errors. Metadata cached in `src/` by CID.
Expect ~11.5k tokens in ~10 min at 20/s. `needs_fix=1` rows are the list; `db_cid_match=0`
rows must be reconciled before generating. Any `error` row → exit 1, rerun.

### 2 · generate

```bash
python3 gen.py --audit audit.csv --export export.csv [--allow-param-diff blockchain,contract,token_id]
#   → dirs/<contract>/<token_id>/metadata.json, plan.csv, blocked.csv
#   --allow-param-diff: only with evidence the work does not read those params (grep its index.html / main.js
#   for URLSearchParams); edition_number can never differ; every accepted change is written to plan.csv changed_params
diff <(python3 -m json.tool src/<old cid>.json) <(python3 -m json.tool dirs/<c>/<t>/metadata.json)   # exactly the rewritten keys
```
`blocked.csv` non-empty → fix the cause (usually `EnsureIPFSReferenceByURI` for a
missing reference) and rerun; gen.py never writes a dir with a non-IPFS URL.

### 2b · prove the rewrite touched nothing else

```bash
python3 check-dirs.py plan.csv       # every dir: same keys, same non-media values, media = plan.csv, source bytes reproduced exactly
```

### 3 · verify the media is public (before touching the chain)

```bash
python3 verify-media.py plan.csv     # every new media CID: 200/206 on ipfs.feralfile.com AND on ≥1 of ipfs.io / dweb.link / pinata
```

### 4 · pin the metadata dirs on prod-02

```bash
# in ff-deploy: make ipfs-port-forward ENV=prod HOST=prod-02
./pin.sh                              # → result.csv, updates/<contract>.csv; HEAD of every new dir via ipfs.bitmark.com must be 200
```
CIDv0, `wrap-with-directory` — same shape as the originals. Resumable.

### 5 · chain, one contract at a time (smallest first, Unsupervised last)

```bash
python3 make-configs.py --sender-account <vault account of the trustee> --expect-trustee 0xbeb9f810862c40a144925f568b1853d72acc492f
cd ../update-token-uri
export UPDATE_CONFIG=$PWD/../metadata-regen/runs/<contract>/config.json RPC_URL=… VAULT_URL=… VAULT_API_KEY=…
node update-token-uri.mjs preflight                 # every row TODO; on-chain ipfsCID == csv old; new dir servable; dry-run ok
# quiet-window check on eth_tx for the trustee (README of update-token-uri, step 2)
node run-all.mjs --limit 1                          # trial → Etherscan tokenURI() + ipfs.bitmark.com/<new>/metadata.json
node run-all.mjs                                    # rest of the contract; resumable via runs/<contract>/progress.json
node update-token-uri.mjs check                     # every row: on-chain ipfsCID == new
```
Each config carries its own `workDir` (`runs/<contract>/`) so contracts never
share `progress.json`. ~55k gas/token; 5,903 tokens ≈ 0.36 ETH at 1.1 gwei;
~15 s per tx (2 confirmations) → Unsupervised ≈ 18 h.

### 6 · DB, then measure

```bash
python3 gen-sql.py result.csv > swaps-update.sql    # UPDATE swaps … WHERE … AND ipfs_cid = <old>; expect UPDATE 1 per row
```
Apply, trigger the OpenSea refresh per contract, rerun the census on prod-02:
the tokens move from `dependent` to `independent`. Final acceptance =
`verify-media.py` again + `audit.py` on the same list showing `needs_fix 0`.

## Files

| | |
|---|---|
| `audit.py` | chain → `audit.csv`, `audit.contracts.csv` |
| `gen.py` | `audit.csv` + DB export → `dirs/`, `plan.csv`, `blocked.csv` |
| `check-dirs.py` | `plan.csv` → proof that each dir differs from its source only in `animation_url`/`image` |
| `verify-media.py` | `plan.csv` → `verify-media.csv` (public-gateway proof for every media CID) |
| `pin.sh` | `dirs/` → prod-02, `result.csv`, `updates/<contract>.csv` |
| `make-configs.py` | `runs/<contract>/config.json` for `tools/update-token-uri` |
| `gen-sql.py` | `result.csv` → `swaps` UPDATEs |
| `src/`, `runs/` | gitignored (fetched originals; live configs / signed txs) |

First use: On Screen Presence's 50 editions were done with the single-contract
ancestor of this tool (`ops/3435-hls-fix/rewilded-metadata-fix/`).

## Data policy

This directory holds **only reusable logic**. Every run's inputs and outputs (audit/plan/result
csv, applied SQL, verification records) belong in an `ops/` directory — the 2026-08/09 run lives in
`ops/bitmark-cdn-retirement/` (see its `SUMMARY.md`). `.gitignore` here excludes all generated data.

---

## Phase-2 additions (V3 docs + V4 dirs, 2026-09-03)

The V2 flow above generalized to the other contract families during CDN
retirement phase 2; the extra tools live in this directory:

| tool | does |
|---|---|
| `v3-doc-regen.py` | V3 docs: fetch by on-chain CID, byte-preserving media-key rewrite — full CDN URLs AND relative `previews/…` paths → `ipfs://<unit>/…`; emits per-contract doc files + `plan.csv` |
| `v4-dir-regen.py` | V4/V4_2 tokenId-named metadata dir rebuild (crystalline: 9,048 docs), driven by the pin-unit registry `dir_cids.csv` |
| `verify-regen.py` | independent verification: reverse-substitution byte proof per doc, media correspondence |
| `pin-docs.py` | uploads regenerated docs to prod-02 via the tunnel (MFS batch, resumable), pins, emits `updates_<contract>.csv` for `../update-token-uri` |

Downstream after regen+pin: per-token txs via `../update-token-uri` (V2/V3),
or ONE `setTokenBaseURI` owner tx via `../update-token-uri/v4-base-uri.mjs`
(V4), then DB align via `../db-align-sql/`. Dir upload for V4 goes through
`../ipfs-mirror/mfs-batch-add.py`.

All regen paths were smoke-tested against live docs with a fake dir-CID map:
relative `_unique-thumbnails` images, dir-URL+query animations, bare-file
thumbnails, and in-dir files all rewrite correctly; non-media bytes proven
identical. Phase-2 receipts: `ops/cdn-retirement-phase2/step3/VERIFICATION.md`.
