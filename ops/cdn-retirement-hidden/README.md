# CDN retirement — hidden exhibitions (6,023 tokens the census never saw)

*Opened 2026-10-05. Owner: Brandon. Parent: `ops/cdn-retirement-phase2/STATUS.md`
(same rules, same tools; read its Gotchas first).*

## What this is

A DB-side scan on 2026-10-05 reported 6,158 tokens whose metadata points at
`cdn.feralfileassets.com`. Checked against the chain the same day — every
token of the seven contracts enumerated from the contract itself
(`tools/contract-audit/enumerate-tokens.py`), every metadata doc fetched by
its on-chain CID:

| exhibition | series | chain · contract | tokens | on chain | scan |
|---|---|---|---|---|---|
| A07 Memento 1 (hidden) | Memento 1 – Study for Unsupervised | Tezos `KT1CPeE8YGVG16xkpoE9sviUYoEzS7hWfu39` | 4,002 of 4,002 | CDN in **every** media field | image only ✗ |
| A06 (hidden) | Study for Unsupervised | ETH V3 `0x7E6c132B8cb00899d17750E0fD982EA122C6b0f2` | 1,002 of 1,002 | image + animation_url CDN | ✓ |
| A04 Luxembourg Art Week (hidden) | A Look of Sheer Delight | Tezos `KT1F6EKvGq8CKJhgsBy3GUJMSS9KPKn1UD5D` | 601 of 601 | CDN in **every** media field | image only ✗ |
| A09 (hidden) | Peer to Peer Launch Party Exclusive | ETH V3 `0xB14b42814895FC1B0A528a475f8A5b070eB4c671` | 302 of 302 | image + animation_url CDN | ✓ |
| A05 (hidden) | Scattered Limbs (Monument 01) | ETH V3 `0xD74745721E3b9c3D784F15bfBA2802fa2e9955d9` | 115 of 335 | image + animation_url CDN (other 220 `ipfs://`) | ✓ |
| no label (hidden) | MONOPOLY SET | ETH V3 `0x14a62abFEC0e09159fBE9c050F3B03044fC7ea52` | 1 of 1 | image CDN, no animation_url | ✓ |
| 024 Peer to Peer (public) | Metaverse Landscape 1: Decentraland Parcel -81, -17 | ETH V3 `0x2A86C5466f088caEbf94e071a77669BAe371CD87` | 0 of 135 | **not CDN** | ✗ |

**On chain: 6,023 tokens to repoint (1,420 ETH + 4,603 Tezos), not 6,158.**

Two corrections to the scan:

- **Decentraland (135) is not a CDN dependency.** `tokenURI` is an inline
  `data:application/json` doc; `image` is `https://ipfs.bitmark.com/ipfs/Qmaf85…`
  and `animation_url` is inline HTML whose iframe loads
  `https://ipfs.bitmark.com/ipfs/QmR7n2…`. No CDN host anywhere in the 135
  docs (`step0/p2p_decentraland_check.csv`). What the scan saw is the DB/API
  value. It depends on our *gateway hostname*, which is the phase-3 class, and
  an inline tokenURI cannot be changed by `updateArtworkEditionIPFSCid` at all.
  Out of scope here. The other 611 tokens of that contract are `ipfs://`
  (phase 2 holds).
- **The two Tezos series are worse than reported.** The scan says "animation_url
  on CDN: none"; on chain `artifactUri`, `displayUri`, `thumbnailUri`, `image`
  and all three `formats[].uri` are CDN URLs — the artwork itself, not just
  the thumbnail.

**The on-chain hostname is dead; the bytes are not.** On 2026-10-05
`cdn.feralfileassets.com` — the host written into all 6,023 docs — no longer
resolved (CNAME to `ddsm7s9hd8znk.cloudfront.net`, no A/AAAA record on the
local resolver, Cloudflare DoH or Google DoH; a control CloudFront host
resolves). The CDN was migrated to `cdn.artworks.feralfile.io` (Brandon,
2026-10-05): same keys, new host, and all 13 units answer there. So wallets
and marketplaces reading the chain see no media for these tokens today, while
the source bytes are intact — step 1 pulls them from the new host.

Why the census missed them: it walks exhibitions the API lists; hidden
exhibitions are not listed. The token lists here come from the contracts.

## Inputs on record (`step0/`, all regenerable)

| file | what |
|---|---|
| `tokens.csv` | 6,243 tokens of the six contracts, `contract,token_id,token_uri`, from chain |
| `eth_audit.csv`, `eth_audit.contracts.csv` | `audit.py` on the four V3 contracts: needs_fix 1,420, errors 0 |
| `tezos_audit.csv` | `tezos-doc-regen.py --audit-only`: needs_fix 4,603, errors 0 |
| `cdn_dirs.csv` | the 13 pin units (6 directories, 7 bare files); none is in the phase-2 registry |
| `p2p_decentraland_check.csv` | the 135 Decentraland tokens, per-token evidence |

Signing, proven by simulation on 2026-10-05 (nothing was signed or sent):

- ETH: `updateArtworkEditionIPFSCid` dry-runs OK from the trustee
  `0xbeb9f810862c40a144925f568b1853d72acc492f` on all four contracts (≈72k
  gas each; an unrelated sender reverts). All four are `FeralfileExhibitionV3`,
  owner `0x1d05cf6c…`, base URI `https://ipfs.bitmark.com/ipfs/`.
  1,420 txs ≈ 102M gas: ≈0.013 ETH at the 0.13 gwei seen that day, ≤0.10 ETH
  at the 1 gwei ceiling; ≈6 h at 15 s/tx.
- Tezos: `tz1fcVFFVujFmnDsWEV1nhGukJTkgXtDKZmm` is a listed trustee on both
  contracts; a 100-token `update_edition_metadata` batch simulates at 54k gas,
  storage 0, fee ≈0.017 tez. 4,603 tokens = 48 operations at `batchSize` 100.

Dry run of the whole regen with placeholder CIDs: 1,420 + 4,603 docs written,
0 failed, every one byte-reversible to its on-chain original.

## Status 2026-10-07 — steps 0–5 DONE (chain repointed, 6,023/6,023 verified); next is step 6, the DB

- **Step 1** 13 units added and pinned on prod-02 (`step1/dir_cids.csv`, 13/13
  verified); afterwards all 30 files were read back through
  ipfs.feralfile.com and their full sha256 equals the CDN fetch (548,091,051
  bytes). Scattered Limbs' thumbnail came out as `QmNNsYCr…` — the CID its 220
  already-`ipfs://` sibling tokens use.
- **Step 2** 1,420 V3 docs + 4,603 Tezos docs regenerated, 0 failed.
- **Step 3** `verify-docs.py`: 6,023 docs byte-reversible to their on-chain
  originals, 13 media targets served (`step3/verify_docs.csv`). Docs pinned
  (six staging roots, `step3/staging_roots.csv`); every one of the 6,023 new
  CIDs is served by the gateway byte-identical to the local file; no duplicate
  new CID inside a contract. Update lists: `step3/updates_<contract>.csv`.
- **Preflights (read-only, nothing signed):** Tezos 601/601 and 4,002/4,002
  TODO, 0 blocked, 100-token batch simulation ✓ on both; ETH MONOPOLY SET 1/1
  TODO.
- Not done by a person yet: opening the three software works in a browser
  (step 3a's last lines). Do it before step 4.

## Runbook

Everything below runs from the repo root. Steps 1b, 3b, 4, 5, 6 need
access only the operator has (prod-02 tunnel, vault, DB). Nothing here refreshes OpenSea (STATUS.md
item 3 stands).

```bash
O=ops/cdn-retirement-hidden
```

### 0 · re-confirm the population (same day as step 4/5; ~2 min)

```bash
RPC_URL=<infura> python3 tools/contract-audit/enumerate-tokens.py \
    0xD74745721E3b9c3D784F15bfBA2802fa2e9955d9 0xB14b42814895FC1B0A528a475f8A5b070eB4c671 \
    0x7E6c132B8cb00899d17750E0fD982EA122C6b0f2 0x14a62abFEC0e09159fBE9c050F3B03044fC7ea52 \
    KT1CPeE8YGVG16xkpoE9sviUYoEzS7hWfu39 KT1F6EKvGq8CKJhgsBy3GUJMSS9KPKn1UD5D --out $O/step0/tokens.csv
git diff --stat $O/step0/tokens.csv          # expect: no change
RPC_URL=<infura> python3 tools/metadata-regen/audit.py $O/step0/tokens.csv --out $O/step0/eth_audit.csv --batch 4 --rps 4
#   expect: 4603 non-Ethereum rows ignored · 1640 tokens: needs_fix 1420, errors 0
python3 tools/metadata-regen/tezos-doc-regen.py --tokens $O/step0/tokens.csv --src $O/src-tezos --audit-only --audit-out $O/step0/tezos_audit.csv
#   expect: audit: 4603 tokens, needs_fix 4603, errors 0
python3 tools/contract-audit/cdn-units.py $O/step0/eth_audit.csv $O/step0/tezos_audit.csv \
    --known ops/cdn-retirement-phase2/step1/dir_cids.csv --out $O/step0/cdn_dirs.csv
#   expect: 13 units to mirror (6 directories, 7 bare files)
```

`git diff --stat $O/step0` should show nothing after these three commands; any
change means the chain moved since 2026-10-05 — read it before going on.

### 1 · mirror the 13 units onto prod-02

**1a · fetch — DONE 2026-10-05** from `https://cdn.artworks.feralfile.io/`
(same keys as the old host): 13 units, 30 files, 548,091,051 bytes, recorded
with sha256s in `step1/mirror_manifest.csv`. Sizes equal the ones the on-chain
docs declare (Memento 1 video 455,180,505 · thumbnails 428,303 / 68,499; Sheer
Delight index 297 · thumbnails 450,840 / 57,059). The three software works
were crawled from `index.html`; their code was read afterwards — no run-time
loads, no external URLs, every reference fetched (Launch Party 13 files incl.
six fonts, Scattered Limbs 3, Sheer Delight 4). The local tree `mirror/` is
gitignored; rebuild it with:

```bash
python3 tools/ipfs-mirror/fetch-units-http.py --dirs $O/step0/cdn_dirs.csv \
    --base https://cdn.artworks.feralfile.io/ --work $O/mirror
diff <(cut -d, -f1-4 $O/mirror/manifest.csv) <(cut -d, -f1-4 $O/step1/mirror_manifest.csv) && echo same bytes
```

**1b · add + pin on prod-02** (tunnel; no bucket needed):

```bash
# in ff-deploy: make ipfs-port-forward ENV=prod HOST=prod-02
LOCAL=1 WORK=$O/mirror ./tools/ipfs-mirror/mirror-add-pin.sh $O/step0/cdn_dirs.csv $O/step1/dir_cids.csv
#   expect: self-test ok, then 13 rows in dir_cids.csv, all gw_ff=ok verified=yes   (0.55 GB — headroom is not a question)
```

### 2 · regenerate the docs (local, no credentials)

```bash
python3 tools/metadata-regen/v3-doc-regen.py --audit $O/step0/eth_audit.csv --dir-cids $O/step1/dir_cids.csv \
    --src $O/src-eth --out-dir $O/step3/v3-docs
#   expect: regen: 1420 docs written, 0 failed
python3 tools/metadata-regen/tezos-doc-regen.py --tokens $O/step0/tokens.csv --src $O/src-tezos \
    --dir-cids $O/step1/dir_cids.csv --out-dir $O/step3/tezos-docs --audit-out $O/step0/tezos_audit.csv
#   expect: regen: 4603 docs written, 0 failed
```

### 3 · verify, then pin the docs

```bash
# 3a · doc integrity + every new media URI served by our gateway (software dirs: index.html scanned)
python3 tools/metadata-regen/verify-docs.py --dir-cids $O/step1/dir_cids.csv \
    --plan $O/step3/v3-docs/plan.csv --src $O/src-eth \
    --plan $O/step3/tezos-docs/plan.csv --src $O/src-tezos --report $O/step3/verify_docs.csv
#   expect: A. 6023 docs, 0 failed; 13 distinct media targets · B. 13 media targets, 0 failed
# open one of each in a browser before going on (params must reach the work):
#   https://ipfs.feralfile.com/ipfs/<Launch Party dir cid>/?edition_number=…   (copy a full animation_url from a new doc)
#   https://ipfs.feralfile.com/ipfs/<Sheer Delight dir cid>/?contract=…&token_id=…&blockchain=tezos
#   https://ipfs.feralfile.com/ipfs/<Scattered Limbs dir cid>/?edition_number=…

# 3b · pin (tunnel open)
python3 tools/metadata-regen/pin-docs.py --plan $O/step3/v3-docs/plan.csv --out-dir $O/step3
python3 tools/metadata-regen/pin-docs.py --plan $O/step3/tezos-docs/plan.csv --out-dir $O/step3
#   expect: six updates_<contract>.csv (1002 / 302 / 115 / 1 / 4002 / 601 rows), staging_roots.csv with 6 rows
```

### 4 · Ethereum — 1,420 trustee txs (vault key, same as phase 2)

```bash
mkdir -p tools/metadata-regen/updates
export RPC_URL=<infura> VAULT_URL=… VAULT_API_KEY=…
cfg() { python3 tools/metadata-regen/make-configs.py --contracts $PWD/$O/step0/eth_audit.contracts.csv \
    --sender-account <vault account of the trustee> --sender-address 0xbeb9f810862c40a144925f568b1853d72acc492f \
    --doc-suffix '' --gateway https://ipfs.bitmark.com/ipfs/; }
# quiet-window check on the server DB before each run — expect 0 rows:
#   SELECT id, nonce, status FROM eth_tx WHERE lower(address) = lower('0xbeb9f810862c40a144925f568b1853d72acc492f') AND status IN ('allocated','broadcast');

# 4a · trial: MONOPOLY SET alone (1 token, 1 tx)
c=0x14a62abfec0e09159fbe9c050f3b03044fc7ea52; cp $O/step3/updates_$c.csv tools/metadata-regen/updates/$c.csv
cfg                                                    # 1 config; the other three print "skip … no updates"
(cd tools/metadata-regen && ./run-contracts.sh --dry-run && ./run-contracts.sh)     # needs bash ≥ 4 (mapfile)
#   look before going on: Etherscan tokenURI(2303…8311) ends in the new CID, and
#   curl -s https://ipfs.bitmark.com/ipfs/<new cid> | python3 -m json.tool | grep image   → "ipfs://<dir cid>/preview.png"

# 4b · the other three (115 → 302 → 1,002, smallest first; ≈6 h; stops on the first failure, rerun resumes)
for c in 0xd74745721e3b9c3d784f15bfba2802fa2e9955d9 0xb14b42814895fc1b0a528a475f8a5b070eb4c671 \
         0x7e6c132b8cb00899d17750e0fd982ea122c6b0f2; do cp $O/step3/updates_$c.csv tools/metadata-regen/updates/$c.csv; done
cfg                                                    # 4 configs
(cd tools/metadata-regen && ./run-contracts.sh --dry-run && BATCH=100 ./run-contracts.sh)
```

Final check — **re-enumerate first**: `audit.py` reuses the `token_uri` column
of its input and does not read the chain for it, so auditing the step-0
`tokens.csv` again just re-reads the pre-rollout docs (needs_fix 1,420).

```bash
RPC_URL=<infura> python3 tools/contract-audit/enumerate-tokens.py 0xD74745721E3b9c3D784F15bfBA2802fa2e9955d9 \
    0xB14b42814895FC1B0A528a475f8A5b070eB4c671 0x7E6c132B8cb00899d17750E0fD982EA122C6b0f2 \
    0x14a62abFEC0e09159fBE9c050F3B03044fC7ea52 --out /tmp/eth_tokens_after.csv
RPC_URL=<infura> python3 tools/metadata-regen/audit.py /tmp/eth_tokens_after.csv --out /tmp/eth_after.csv --batch 4 --rps 4
#   expect: 1640 tokens: needs_fix 0
```
**Outcome 2026-10-06: all four contracts complete (`run-contracts.sh`: 4/4);
re-audit from the chain 2026-10-07: 1,640 tokens, needs_fix 0, and every one
of the 1,420 on-chain doc CIDs equals the planned new CID.**

### 5 · Tezos — 48 trustee operations (vault key)

```bash
cp $O/tezos-sheer-delight.config.example.json $O/tezos-sheer-delight.config.json   # fill senderAccount
cp $O/tezos-memento1.config.example.json      $O/tezos-memento1.config.json        # fill senderAccount
cd tools/update-tezos-metadata
export VAULT_URL=… VAULT_API_KEY=…
# Sheer Delight first (601, the smaller one)
export UPDATE_CONFIG=$PWD/../../$O/tezos-sheer-delight.config.json
node update-tezos-metadata.mjs preflight        # expect: 601 to do · 0 already done · 0 blocked; simulation ✓
# tzkt: no pending operation from tz1fcVFF… (the server mints from the same key)
node update-tezos-metadata.mjs run --limit 1    # one token, one op → check it on tzkt + objkt before going on
node update-tezos-metadata.mjs run              # 7 ops
node update-tezos-metadata.mjs check 2>&1 | tail -1     # expect: 601/601 updated
# then Memento 1
export UPDATE_CONFIG=$PWD/../../$O/tezos-memento1.config.json
node update-tezos-metadata.mjs preflight        # expect: 4002 to do · 0 blocked
node update-tezos-metadata.mjs run --limit 1
node update-tezos-metadata.mjs run              # 41 ops
node update-tezos-metadata.mjs check 2>&1 | tail -1     # expect: 4002/4002 updated
cd ../..
```

Final check — re-enumerate first (same reason as step 4):

```bash
python3 tools/contract-audit/enumerate-tokens.py KT1CPeE8YGVG16xkpoE9sviUYoEzS7hWfu39 KT1F6EKvGq8CKJhgsBy3GUJMSS9KPKn1UD5D --out /tmp/tz_tokens_after.csv
python3 tools/metadata-regen/tezos-doc-regen.py --tokens /tmp/tz_tokens_after.csv --src $O/src-tezos --audit-only --audit-out /tmp/tezos_after.csv
#   expect: audit: 4603 tokens, needs_fix 0
```
**Outcome 2026-10-07: both contracts complete (`check`: 601/601, 4002/4002);
re-audit from the chain: 4,603 tokens, needs_fix 0, and every on-chain
`token_info` equals the planned new CID (4,603/4,603).**

### 6 · DB follows the chain (DBeaver or psql)

No export needed: the old→new mapping rides inside the SQL.

```bash
python3 tools/db-align-sql/gen-map-sql.py --updates $O/step3/updates_*.csv --out-dir $O/step2
#   → step2/01-precheck.sql (read-only), step2/02-align.sql (BEGIN … UPDATE … counts; no COMMIT)
```

1. Run `01-precheck.sql`. Expect, per series and in the TOTAL row:
   `found = in_map = holds_old`, `holds_new = 0`, `holds_other = 0`
   (TOTAL in_map 6023). Anything else: stop.
2. In DBeaver switch the connection to **manual commit** (toolbar
   Auto-commit toggle off), run `02-align.sql` as a script (Alt+X). It prints
   `UPDATE 6023` and the counts again: every series `holds_new = in_map`,
   `holds_old = 0`, `holds_other = 0`.
3. Only then `COMMIT;` — or `ROLLBACK;` if a number is off.

`artworks.id` = token id and `metadata.ipfs_cid` = bare doc CID on both
chains (spot-checked against the API 2026-10-05). Reference rows
(`gen-reference-sql.py`) are optional and need the export in
`step2/export-tokens.sql` (psql only); they will report unmapped rows because
the DB's display thumbnails for the Tezos series are a later version than the
one on chain.

### 7 · record

Update `ops/cdn-retirement-phase2/STATUS.md` (new closed item) and
`data/updates.json`; the status page counts only census exhibitions, so its
numbers do not move. Decide separately whether hidden exhibitions belong in
the census universe.

## Open questions

1. The old P2P contract's 47 outside-held tokens (phase-2 STATUS item 4,
   decided out of scope) name the same dead hostname; that decision was taken
   while the old host still answered.
2. Hidden exhibitions are still outside the census universe.
