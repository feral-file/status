# CDN retirement — hidden exhibitions (6,023 tokens the census never saw)

*Opened 2026-10-05, CLOSED 2026-10-07. Owner: Brandon. Parent: `ops/cdn-retirement-phase2/STATUS.md`
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
  docs (checked token by token, 2026-10-05). What the scan saw is the DB/API
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
the source bytes were intact — they were pulled from the new host.

Why the census missed them: it walks exhibitions the API lists; hidden
exhibitions are not listed. The token lists here come from the contracts.

## Outcome

| step | result |
|---|---|
| 1 · media | 13 units (548,091,051 bytes, 30 files) fetched from `cdn.artworks.feralfile.io`, added and pinned on prod-02 (`step1/dir_cids.csv`), every file read back through ipfs.feralfile.com with the same sha256 (`step1/mirror_manifest.csv`). Scattered Limbs' thumbnail came out as `QmNNsYCr…`, the CID its 220 already-`ipfs://` siblings use |
| 2–3 · docs | 1,420 V3 + 4,603 Tezos docs regenerated (media fields only), proven byte-reversible to the on-chain originals, pinned under six staging roots (`step3/staging_roots.csv`); each new CID served byte-identical; no duplicate CID in a contract. Old→new per token: `step3/updates_<contract>.csv` |
| 4 · Ethereum | 1,420 `updateArtworkEditionIPFSCid` txs by the trustee `0xbeb9f810…`, `run-contracts.sh` 4/4 complete 2026-10-06; re-enumerated from chain 2026-10-07: 1,640 tokens, needs_fix 0, 1,420/1,420 at the planned CID |
| 5 · Tezos | 48 `update_edition_metadata` ops by the trustee `tz1fcVFF…` (batch 100), 2026-10-07; re-enumerated: 4,603/4,603 at the planned CID |
| 6 · DB | `artworks.metadata.ipfs_cid`: pre-check every series `found = in_map = holds_old`, `UPDATE 6023`, post-check `holds_new = in_map`, committed 2026-10-07 (DBeaver). API spot-check serves the new CIDs |
| 8 · OpenSea | `refreshOpenSeaTokensMetadata` per contract (1 / 115 / 302 / 1,002). Side finding: Scattered Limbs showed 266 items, not 335 — 69 of the 220 *untouched* tokens had no OpenSea item at all (`step8/opensea_delist_scattered_limbs.csv`, before/after); a refresh of those 69 made OpenSea index them: 69/69 Item afterwards. Not caused by this migration; the two older OpenSea collections for the series are one delisted, one empty |

Recorded elsewhere: `ops/cdn-retirement-phase2/STATUS.md` item 11,
`data/updates.json` 2026-10-07.

## What is kept, what was deleted (repo-cleanup policy)

Kept: this record; `step0/cdn_dirs.csv` (unit list) and
`eth_audit.contracts.csv`; `step1/dir_cids.csv` (pin-unit registry) and
`mirror_manifest.csv` (sha256 of what was fetched); `step2/export-tokens.sql`
(a query); `step3/updates_*.csv` (the 6,023 old→new doc mappings — the
*before* state) and `staging_roots.csv`; `step8/opensea_delist_scattered_limbs.csv`
(a before/after of OpenSea's state that cannot be re-measured); the two Tezos
config templates.

Deleted after the close-out, all regenerable: the chain enumeration and audits
(`enumerate-tokens.py`, `audit.py`, `tezos-doc-regen.py --audit-only` — they
now read the post-rollout chain), the fetched originals (`src-*`: the old
docs are the `old_metadata_cid` column, still on ipfs.bitmark.com), the
regenerated doc trees and the verifier report (the docs are pinned and
served), the local mirror (pinned), the generated align SQL
(`gen-map-sql.py` from `updates_*.csv`), the OpenSea refresh payloads
(`{"contractToTokenIDs": {"<contract>": [token ids of updates_<contract>.csv]}}`),
run state (progress files, vault request files, logs — the chain is the
receipt), and the filled Tezos configs (vault account id).

## How it was done (the procedure, reusable for the next hidden contract)

Everything from the repo root; `O=ops/cdn-retirement-hidden`. Tools are
generic; only the contract list and this directory are specific.

```bash
# 0 · population from the chain, not from a census
RPC_URL=<infura> python3 tools/contract-audit/enumerate-tokens.py <0x… KT1… …> --out $O/step0/tokens.csv
RPC_URL=<infura> python3 tools/metadata-regen/audit.py $O/step0/tokens.csv --out $O/step0/eth_audit.csv --batch 4 --rps 4
python3 tools/metadata-regen/tezos-doc-regen.py --tokens $O/step0/tokens.csv --src $O/src-tezos --audit-only --audit-out $O/step0/tezos_audit.csv
python3 tools/contract-audit/cdn-units.py $O/step0/eth_audit.csv $O/step0/tezos_audit.csv \
    --known ops/cdn-retirement-phase2/step1/dir_cids.csv --out $O/step0/cdn_dirs.csv

# 1 · media: fetch over HTTP (no bucket), add + pin through the prod-02 tunnel
python3 tools/ipfs-mirror/fetch-units-http.py --dirs $O/step0/cdn_dirs.csv --base https://cdn.artworks.feralfile.io/ --work $O/mirror
LOCAL=1 WORK=$O/mirror ./tools/ipfs-mirror/mirror-add-pin.sh $O/step0/cdn_dirs.csv $O/step1/dir_cids.csv

# 2–3 · docs: regenerate, verify, pin
python3 tools/metadata-regen/v3-doc-regen.py --audit $O/step0/eth_audit.csv --dir-cids $O/step1/dir_cids.csv --src $O/src-eth --out-dir $O/step3/v3-docs
python3 tools/metadata-regen/tezos-doc-regen.py --tokens $O/step0/tokens.csv --src $O/src-tezos --dir-cids $O/step1/dir_cids.csv --out-dir $O/step3/tezos-docs --audit-out $O/step0/tezos_audit.csv
python3 tools/metadata-regen/verify-docs.py --dir-cids $O/step1/dir_cids.csv --plan $O/step3/v3-docs/plan.csv --src $O/src-eth \
    --plan $O/step3/tezos-docs/plan.csv --src $O/src-tezos --report $O/step3/verify_docs.csv
python3 tools/metadata-regen/pin-docs.py --plan $O/step3/v3-docs/plan.csv --out-dir $O/step3
python3 tools/metadata-regen/pin-docs.py --plan $O/step3/tezos-docs/plan.csv --out-dir $O/step3

# 4 · Ethereum (vault): updates_<c>.csv → tools/metadata-regen/updates/<c>.csv, make-configs.py
#     (--sender-address <trustee> --doc-suffix '' --gateway https://ipfs.bitmark.com/ipfs/),
#     quiet-window check on eth_tx, run-contracts.sh --dry-run, then run-contracts.sh (bash ≥ 4);
#     smallest contract first as the trial.
# 5 · Tezos (vault): copy tezos-*.config.example.json → .config.json, fill senderAccount;
#     update-tezos-metadata.mjs preflight → run --limit 1 → run [--yes] → check.
# 4/5 final check: re-enumerate FIRST (audit.py reuses the token_uri column), then audit → needs_fix 0.

# 6 · DB (DBeaver or psql): export-free, self-checking
python3 tools/db-align-sql/gen-map-sql.py --updates $O/step3/updates_*.csv --out-dir $O/step2
#     01-precheck.sql (read-only) → 02-align.sql with auto-commit off → read counts → COMMIT

# 8 · OpenSea: back-office refreshOpenSeaTokensMetadata, one task per contract, only the repointed
#     tokens; smallest first. Safe here because none of the four is a paused special-project
#     collection, the three Decentralized ones are bound to our uuid, Scattered Limbs is Centralized
#     (ops/opensea-metadata-path/README.md).
```

Things learned, in case the next run hits them: the new CDN host rewrites
HTML at the edge unless the request carries an `Accept` header (the fetch tool
sends one and refuses the beacon); Infura throttles plain `eth_call` batches
to ~5/s — enumerate through Multicall3; `update-tezos-metadata.mjs run` scans
every csv row on chain before signing (minutes for 4,002 tokens; it now prints
progress); OpenSea tokens it never indexed come back with a refresh.

## Open

1. Hidden exhibitions are outside the census universe; the status page never
   counted these 6,023 and still does not.
2. The old P2P contract's 47 outside-held tokens (phase-2 STATUS item 4,
   decided out of scope) name the same dead hostname.
