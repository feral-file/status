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
`ipfs://` on chain and every one of their media CIDs is served by prod-02.** The CDN
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
- Resolvability of the docs' media CIDs (`Range: bytes=0-0` GET):
  - indexed 8: 227 distinct CIDs — **227/227 on `ipfs.feralfile.com`**, 226/227 on ipfs.io
    (`media_cid_probe.csv`);
  - un-indexed 30: 141 distinct CIDs — **141/141 on `ipfs.feralfile.com`**; ipfs.io 26 ok +
    115 HTTP 429 (rate-limited, not a miss). A paced re-probe (12 s apart) was started and
    killed by the OS before finishing; rerun it before claiming public resolvability for
    this class: `round2_media_cid_reprobe.csv` holds the 115 CIDs, probe each on ipfs.io
    with ≥10 s spacing and record to `round2_media_cid_reprobe_slow.csv`.
  prod-02 runs `Gateway.NoFetch`, so a 200/206 there means the bytes are locally present.
  Whether they are explicitly pinned or only cached is not distinguishable from outside —
  feed the 368 CIDs to the next `tools/pin-referenced` run (they are not in any DB export).

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
- Fold the 368 media CIDs into `tools/pin-referenced`.

## Files

`population.csv` (the 103-contract table) · `deployer_created_contracts.csv` ·
`other_deployers_created.csv` · `indexer_contracts_feralfile.csv` ·
`indexer_releases_feralfile.csv` · `slug_contracts.csv` · `candidate_contracts*.csv` ·
`round2_contracts_blockscout.csv` · `special_project_tokens.csv` ·
`special_project_summary.csv` · `round2_tokens.csv` · `round2_summary.csv` ·
`round2_chain_tokens.csv` · `round2_chain_summary.csv` · `round2_ffapi_tokens.csv` ·
`media_cid_probe.csv` · `round2_media_cid_probe.csv` · `round2_media_cid_reprobe*.csv` ·
`zero_token_contracts_chain.csv` (superseded: its "no code" verdicts were 1rpc rate-limit
nulls, see `round2_contracts_blockscout.csv`) · `tools/` (walker, auditors, slug scraper).
