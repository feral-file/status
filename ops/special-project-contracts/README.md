# Special-project contracts — media dependency + OpenSea collection uuid

*Measured 2026-09-08 (Brandon). Track opened by OpenSea's 2026-09-04 audit
(`ops/opensea-metadata-path/ryan_reply_2026-09-04.md`): 57 collections on their side belong
to contracts we deployed but never published as an exhibition. Two questions, one
population: (a) does their media depend on the CDN? (b) how does their `collection_uuid`
get pinned? This directory answers (a) in full and gives (b) its population.*

## Answer in one paragraph

Every Ethereum contract created by the Feral File deployer (`0x1d05cf6c…`, 103 contracts,
2021-10 → 2025-07) was classified. Outside the 45 platform exhibition contracts and 18
helpers/tests, there are **40 NFT contracts, 1,588 tokens** that no census, DB table or
phase-2 tool has ever looked at. **1,335 of them (38 contracts, the actual "special
projects": a2p, Machine Hallucinations, Aorist-era and 2024-25 drops) are already 100%
`ipfs://` on chain and every one of their 368 media CIDs is on prod-02 — served, and
since 2026-09-08 explicitly pinned (367 had been cache-only).** The only CDN
dependency (200 tokens) sits on **two superseded contracts** — `Feral File — Peer to Peer`
V3_1 `0x22e130a4…` (251 tokens) and `Feral File 007` `0xc764a826…` (2 tokens) — each
replaced within days by the official contract that the DB, census and collectors use
(evidence below). Nothing on them needs repointing; they should be recorded as superseded,
not as a remediation population.

## Definition (server, `api/swap.go`) and why nothing saw these

A non-exhibition contract is served when `exhibition_contract` has no row for the address
and `owner() == opensea.deployer_address`: the API reads `tokenURI` on chain, fetches the
doc from IPFS, rewrites `ipfs://` to our gateway, and derives
`collection_uuid = uuid5(ns, doc.collection_name)` **per token**. No DB rows exist for
these tokens → the census (`token-health-monitor/discovery.py` walks FF-API exhibitions →
exhibition-contracts → artworks) excludes them by construction, and so do the phase-2
tools. The indexer (`indexer-v2.feralfile.com`) holds only 9 of the 40 (see below).

## Population — how it was built (`population.csv`, 103 rows)

1. **Ryan's list** carries no contract addresses for this class (`eth_contracts` empty on
   all 81 rows); OpenSea collection pages embed a contract for some (21 real ones,
   `slug_contracts.csv`) but 41 pages only show template noise and 19 are 404.
2. **Blockscout, contracts created by the deployer** (`deployer_created_contracts.csv`):
   557 txs → **103 contracts**. This is the authoritative population. The other creators
   behind the 8 platform contracts not on that list (`other_deployers_created.csv`:
   `0x4f269268…` = the V4/V4_1 family incl. Truth, `0x2033606b…` and `0x8f3db771…` =
   test contracts only) add no special projects.
3. **Indexer walk** (`tools/indexer-walk.py`, 242,009 Ethereum tokens across all
   publishers; raw output deleted, derived table `indexer_contracts_feralfile.csv`): Feral
   File = 24,879 tokens on 60 contracts, **51 platform + 9 non-platform** — the 8
   a2p/Machine-Hallucinations-era contracts plus the P2P V3_1. **The 30 Aorist-era and
   2024-25 contracts are not indexed at all** (registry gap: `deployer_addresses` in
   `publisher.json` does not pull them in) — an ff-indexer-v2 issue to file.
   Two platform contracts are also absent (`0x87355eb8…` internal auction, `0x14a62abf…`).

| class | contracts | tokens | media all `ipfs://` | media on FF CDN |
|---|---|---|---|---|
| platform exhibition contracts | 45 | (census scope) | — | — |
| special projects, indexed (a2p-v1/v2, MH Coral ×2, Minoriea, Take Over Miami, self-contained, Social Sacrifice) | 8 | 992 | 992 | 0 |
| special projects, un-indexed (AoristArt ×9, Coral Arena ×2, Hall of Visions, Mushroom Cloud, Quayola ×3, Reisinger ×4, chromatophores, Neural Zoo ×2, Temporally Uncaptured ×2, Artificial Natural History ×2, Take Over Madrid, Collide, Decohering Delineation, …) | 30 | 343 | 343 | 0 |
| **superseded** contract: `Feral File — Peer to Peer` V3_1 `0x22e130a4…` (METASOTO, Winslow Homer's Croquet Challenge, Wheel of Life, Bend, Caryatid ×4, … — 15 Peer to Peer series, AE/PP-style editions) | 1 | 251 | 53 | **198** |
| **superseded** contract: `Feral File 007` `0xc764a826…` (2021) | 1 | 2 | 0 | **2** |
| helpers / tests (TokenBatchTransfer, Vault, EnglishAuction, SeriesRegistry, MerkleRegistry, OwnerData, LibBytes, unnamed 0-tx) | 18 | — | — | — |

## How the media was measured

- Indexed contracts: `tools/audit-contracts.py` — every token's raw on-chain doc
  (`metadata.origin_json`) from the indexer, `image`/`animation_url` classified by host
  (`special_project_tokens.csv` 992 rows, `special_project_summary.csv`; the P2P contract's
  206 indexed tokens are in `round2_tokens.csv`).
- Un-indexed contracts: Blockscout token instances + metadata
  (`round2_chain_tokens.csv`, 596 rows incl. P2P's 251), and for the 247 tokens Blockscout
  had no metadata for, the FF API's own non-exhibition path
  (`/api/contracts/<c>/tokens/<id>` → chain `tokenURI` → IPFS): **247/247 HTTP 200, all
  `ipfs://`** (`round2_ffapi_tokens.csv`). Contract facts: `round2_contracts_blockscout.csv`.
- Resolvability + **pin status on prod-02** (the serving node, `Gateway.NoFetch`):
  - indexed 8: 227 distinct media CIDs, un-indexed 30: 141 — **368/368 served by
    `ipfs.feralfile.com`** (`media_cid_probe.csv`, `round2_media_cid_probe.csv`).
  - **Pin check through the kubo API (2026-09-08, `prod02_pin_status_before.csv`): only 1 of
    the 368 was a recursive pin root; 367 were present as unpinned cache** — the same
    survive-only-because-GC-is-off exposure found for platform tokens on 2026-08-28
    (ff-deploy#28 policy: everything referenced must be pinned). Fixed on the spot with
    `tools/pin-referenced/batch_pin.py` (local pinset operation, no fetch):
    **368/368 now recursive pin roots** (`prod02_pin_status.csv`; recursive pins 82,555 →
    82,922). Public-gateway reachability was deliberately not re-measured (decision
    2026-09-08: pinned on prod-02 is the requirement).

## The two CDN-dependent contracts are superseded (verified 2026-09-08)

**`0x22e130a4…` P2P V3_1** (deployed 2022-11-21; all its activity is 2022-11-21 → 11-26):
- **204 of 251 tokens sit in the Feral File vault-trustee wallet `0xbeb9f810…`** — never
  distributed. 150 of them have a same-named twin on the official V3 `0x2A86C546…`.
- The other **47 are all AE/PP editions** (artist editions / publisher proofs) sent to 15
  wallets on 2022-11-21; **every one has a same-named twin on the official V3** — 45 held
  there by a different wallet, 2 by the same wallet (`Winslow Homer's Croquet Challenge
  AE`, `0x63ff78ef…`). I.e. the AE/PP were re-issued on V3 and these are stale duplicates.
- The official V3 (584 tokens today, 611 at phase-2 time) holds the same 15 series incl.
  46 AE/PP-named tokens, and is what the DB's `exhibition_contract`, the census and
  phase-2 covered.
- `tokenURI` here is `https://ipfs.bitmark.com/ipfs/<docCID>` (V3 shape); the contract
  has `updateArtworkEditionIPFSCid` + `setTokenBaseURI`, so a fix *could* be done (docs'
  296 CDN refs are all inside phase-2 pin units), but there is nothing to fix for
  collectors — the live editions are on V3.

**`0xc764a826…` Feral File 007** (`FeralfileExhibition`, 2021-10-26, compiler 0.8.0, the
pre-V2 contract with `swapArtworkFromBitmark`):
- Both remaining tokens (`Vague Recollection #67`, `Solstice Sky Dream #40`, exhibition
  "Reflections in the Water") were **returned to the deployer wallet on 2021-11-22** and
  sit there today; **the same editions exist on the official V2 `0x29C9E04E…`** held by
  the original collectors (e.g. `0xE2dbEB9e…`, the wallet that received #67 on this
  contract first). Classic early-swap → re-swap-on-V2 history.

**Recommendation**: classify both as *superseded contracts* in `population.csv` (done) and
on any future status-page scope note; do not spend txs on them. Optional hygiene: burn the
204 + 2 vault/deployer-held tokens so they stop surfacing on OpenSea/indexers (a decision
for Sean; not required for permanence).

## Open

- (b) `collection_uuid` pinning for the 38 special-project contracts: per-token uuid5 of
  `collection_name` → one stored value per collection, server-side. The population and
  every token's `collection_name` are in this directory (`special_project_tokens.csv`,
  `round2_chain_tokens.csv`, `round2_ffapi_tokens.csv`). Design + Ryan's 57-row mapping
  pending (`ops/opensea-metadata-path/README.md` § special-project class).
- File: ff-indexer-v2 (30 deployer-created ERC-721 contracts not indexed),
  agentic-workflows (census cannot take a contract list).
- Keep this directory's 368 CIDs in future `tools/pin-referenced` runs (they are in no DB export): `prod02_pin_status.csv` is the list.

## Files

`population.csv` (the 103-contract table) · `deployer_created_contracts.csv` ·
`other_deployers_created.csv` · `indexer_contracts_feralfile.csv` ·
`indexer_releases_feralfile.csv` · `slug_contracts.csv` · `candidate_contracts*.csv` ·
`round2_contracts_blockscout.csv` · `special_project_tokens.csv` ·
`special_project_summary.csv` · `round2_tokens.csv` · `round2_summary.csv` ·
`round2_chain_tokens.csv` · `round2_chain_summary.csv` · `round2_ffapi_tokens.csv` ·
`media_cid_probe.csv` · `round2_media_cid_probe.csv` · `prod02_pin_status_before.csv` · `prod02_pin_status.csv` · `prod02_unpinned_cids.txt` ·
`zero_token_contracts_chain.csv` (superseded: its "no code" verdicts were 1rpc rate-limit
nulls, see `round2_contracts_blockscout.csv`) · `tools/` (walker, auditors, slug scraper).
