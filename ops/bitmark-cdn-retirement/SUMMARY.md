# Goal 2 — 5,880 migrated Bitmark-era V2 tokens moved from CDN to `ipfs://` (done 2026-09-01)

Execution record for goal 2 of `ops/bitmark-cdn-retirement.md` (feral-file/feral-file#3435):
every already-swapped Ethereum token whose **on-chain** metadata still pointed
`animation_url` / `image` at `cdn.feralfileassets.com` / `imagedelivery.net` now points at
`ipfs://` CIDs from `ipfs_reference`. Tools: `tools/metadata-regen/` (+ `tools/update-token-uri`).

## Numbers

| | |
|---|---|
| Audited on chain (2026-08-28, `tokenURI` of every migrated ETH token) | 11,537 tokens / 18 contracts |
| Fixed | **5,880** tokens / **17** `FeralfileExhibitionV2` contracts |
| Chain txs | 5,880 × `updateArtworkEditionIPFSCid` by trustee `0xbeb9f810…492f` (vault-signed), ~66k gas each, fee ceiling 1 gwei; finished 2026-08-31, `check` 17/17 green |
| DB (2026-09-01) | `swaps.ipfs_cid` ×5,880 + `artworks.metadata.ipfs_cid` ×25 = 5,905 rows (`db/swaps-update_2026-09-01.sql`), pre/post-counted |
| OpenSea | one `refreshOpenSeaTokensMetadata` task over all 5,880 (back-office) |
| Acceptance | re-audit: needs_fix 0, errors 0 · DB recount: already_new 5,880, mismatches 0 · media: 436/436 distinct CIDs on ipfs.feralfile.com and ≥1 public gateway |

## Files

| file | what |
|---|---|
| `v2_cdn_tokens_export_2026-08-28.csv` | step-0 DB export (11,537 rows: token, edition, swaps cid, references, medium) |
| `audit_2026-08-28.csv` (+`.contracts.csv`) | chain-built audit: per-token `tokenURI` CID, media classes, `needs_fix`; per-contract trustee/owner |
| `plan.csv` | per-token rewrite record: old/new `animation_url`+`image`, `source` (chain / db), `changed_params`, `token_id_db`, `db_cid` |
| `result.csv` | **the mapping**: contract, edition, token_id, old→new metadata dir CID (CIDv0, pinned on prod-02) |
| `verify-media_2026-09-01.notes.md` | media verification record: 436/436, with the 21 transient gateway failures explained |
| `db/swaps-update_2026-09-01.sql` | DB change as applied (WHERE pins the old value; 5,905 × UPDATE 1) |
| `db/primordium-*` | the Primordium incident analysis (below) |

The 5,880 replacement `metadata.json` dirs are not committed: `gen.py` regenerates them
byte-identically from `audit` + the export (verified via `check-dirs.py`, 5,880/5,880), and the
bytes are pinned on prod-02 and referenced on chain.

## Decisions & findings (details in `tools/metadata-regen/README.md`)

- **Chain is the source of truth**: the census/API overlays `alternativePreviewURI`; the fix list was rebuilt from `tokenURI`. 228 DB≠chain rows differed only in `timestamp`/`prev_provenance` (accepted; SQL keyed on the DB's value).
- **Byte-preservation**: every rewrite changed only `animation_url`/`image`; all other keys byte-identical (server JSON shape), including the 326 legacy 2021 6-key metadata (kept in their original shape; edition checked via the `name` "#N" suffix, 326/326).
- **Query params preserved**: `?edition_number=…` kept equal on 72 tokens; 15 –GRAPH tokens dropped `blockchain/contract/token_id` under `--allow-param-diff` after verifying `main.js` reads only `edition_number`.
- **Primordium (`0x513ac4…`)**: a 2025-12-26 job re-registered 28 tokens on chain against dirs pinned on the discontinued Infura IPFS (25 recorded in `artworks.metadata.ipfs_cid`, 3 nowhere); `swaps` kept 2022/2023 values. All 28 rebuilt against the current `ipfs_reference` (2024-09 previews), consistent with the contract's other 51 tokens.
- One `swaps.token` stored as 64-hex (For Your Eyes Only ed 96) — same uint256; handled via `token_id_db`.
- `0x377d8e…` (The Experiment, 209 tokens): already all-IPFS, out of scope.

Exit condition met: census `dependent` = 0 for migrated Bitmark-era tokens (to be confirmed by the next census run on prod-02).
