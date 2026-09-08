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

## The 200 CDN-dependent tokens — what the fix would be

**`0x22e130a4…` (P2P V3_1, verified on Sourcify as `FeralfileExhibitionV3_1`)**: docs are
server-generated (`id`, `symbols`, `metadata_version` keys), media point at
`previews/<series>/<ts>/…` and `thumbnails/…` of 15 Peer to Peer series that live in our DB
under the V3 contract `0x2A86C546…`. All 296 CDN references fall inside 26 existing phase-2
pin units (`step1/dir_cids.csv`), so the bytes are pinned already. The contract exposes
`updateArtworkEditionIPFSCid(uint256,string)` (trustee) and `setTokenBaseURI(string)` —
the V3 phase-2 path applies unchanged: byte-preserving doc regen (`v3-doc-regen.py` over
the 198 docs) → pin → ~198 trustee txs. No DB rows to align. **Not started; needs a
decision that this contract is in scope** (it is not on the status page and not an
exhibition contract, but it is Feral File-published work).
**`0xc764a826…` (Feral File 007, 2021, 2 tokens)**: same shape, 2 docs.

## Open

- (b) `collection_uuid` pinning for the 38 special-project contracts: per-token uuid5 of
  `collection_name` → one stored value per collection, server-side. The population and
  every token's `collection_name` are in this directory (`special_project_tokens.csv`,
  `round2_chain_tokens.csv`, `round2_ffapi_tokens.csv`). Design + Ryan's 57-row mapping
  pending (`ops/opensea-metadata-path/README.md` § special-project class).
- Decide scope for the 200 CDN-dependent exhibition-era tokens (above).
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
