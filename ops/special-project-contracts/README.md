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
since 2026-09-08 explicitly pinned (367 had been cache-only).** The CDN
dependency is concentrated in **two exhibition-era extra contracts: 200 tokens** — 198 on
`Feral File — Peer to Peer` (`0x22e130a4…`, a `FeralfileExhibitionV3_1`, 251 tokens) and 2
on `Feral File 007` (`0xc764a826…`, 2021). All 296 CDN references on the P2P contract are
already inside phase-2's pin units (26 of the 104), so that fix is doc regen + per-token
`updateArtworkEditionIPFSCid` txs, no new bytes.

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
| exhibition-era extra: `Feral File — Peer to Peer` V3_1 `0x22e130a4…` (METASOTO, Winslow Homer's Croquet Challenge, Wheel of Life, Bend, Caryatid ×4, … — 15 Peer to Peer series, AE/PP-style editions) | 1 | 251 | 53 | **198** |
| exhibition-era extra: `Feral File 007` `0xc764a826…` (2021) | 1 | 2 | 0 | **2** |
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

## The 200 CDN-dependent tokens — superseded deployments, mostly FF-held

Checked 2026-09-08 (Blockscout owners + transfer history):

**`0x22e130a4…` (P2P V3_1, created 2022-11-21)** is the first Peer to Peer deployment; the
official V3 contract `0x2A86C546…` was created five days later (2022-11-26) and is the only
one bound in the DB. All 488 transfers on the old contract happened 2022-11-21 → 11-26 and
nothing since. **204 of the 251 tokens sit in the Feral File vault-trustee wallet
(`0xbeb9f810…`); 47 are in 15 outside wallets** (`0xcf577a8d…` 15, `0xffaaf237…` 8, …),
moved during those five days. Verified on Sourcify as `FeralfileExhibitionV3_1`; `tokenURI`
= bare doc CID on ipfs.bitmark.com; `updateArtworkEditionIPFSCid` + `setTokenBaseURI`
present. Media: 198 CDN-dependent (103 cdn/cdn, 73 relative-`previews/`+cdn, 22 cdn only)
across 15 P2P series (METASOTO 67, Winslow Homer's Croquet Challenge 53, Wheel of Life 11,
Titled 11, Bend 10, Club Rothko 8, Marisol/Daphne/Auriea 6, eight 4-token series); 53 are
the Decentraland parcel work (ipfs image + inline HTML). All 296 CDN refs are inside 26
existing phase-2 pin units, so a fix would be the V3 phase-2 path (doc regen → pin → ~198
trustee txs, ~0.013 ETH at 1 gwei; DB rows to be checked from an export first).

**`0xc764a826…` (`FeralfileExhibition`, 2021-10-26)** is the pre-V2 contract for 007
*Reflections in the Water* (official contract in the DB: `0x29C9E04E…`). Its 2 tokens
(Vague Recollection #67, Solstice Sky Dream #40) are **both held by the deployer wallet**,
last activity 2021-11-22. Abandoned.

**Decision (Brandon, 2026-09-08): both are superseded deployments with official
counterparts; not in scope for CDN retirement.** The one residual to be aware of: the 47
old-P2P tokens in outside wallets still resolve to CDN-hosted media via `tokenURI`. If that
ever matters, the fix above applies to exactly those 47.

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
