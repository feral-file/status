# Bitmark-era works: every migrated token's metadata points at CIDs — execution plan

*Drafted 2026-08-28 from the 2026-08-25 census and feral-file-server. Owner: Brandon. Tracks feral-file/feral-file#3435 (reference phase) and #3463.*

Scope is deliberately narrow. Whether feralfile.com or FF1 fetch from the CDN is not this plan's concern. Two goals only:

1. **Every future Bitmark → Ethereum/Tezos swap mints metadata whose media resources are `ipfs://` CIDs, never CDN URLs.**
2. **Every already-swapped token whose on-chain metadata still points at the CDN gets its on-chain data updated to CIDs.**

The bytes are already published: all 215 Bitmark-era series are pinned on prod-02 (mirrored from the custody node) and every `ipfs_reference` CID for these works is pinned and announced (74,311 recursive pins, 2026-08-28).

## Audit (census 2026-08-25, Bitmark-era exhibitions only)

| | Works | Media in on-chain metadata |
|---|---|---|
| Migrated to Tezos | 701 | **701 all `ipfs://`** — nothing to do |
| Migrated to Ethereum | 11,537 | 5,634 all `ipfs://` · **5,903 point at the CDN** (`animation_url` 5,096 rows, `image` 4,986 rows; 878 `image` rows on `imagedelivery.net`, 45 `animation_url` on other hosts) |
| Still on Bitmark | 4,959 | no on-chain metadata (goal 1 covers them when they swap) |

The 5,903 sit on **17 contracts, all `FeralfileExhibitionV2`** (Unsupervised 4,310 · Social Codes 278 · Field Guide 251 · The Bardo 151 · Fragments of a Hologram Rose 146 · For Your Eyes Only 124 · Reflections in the Water 116 · –GRAPH 89 · P1×3L 84 · The Long Cut 79 · On Screen Presence 73 · Instructions Follow 52 · Ten Whistlegraphs 45 · Primordium 40 · Polyarrythmia 28 · WETWARE 22 · Infinite Entropy 15). Per-token list: `ops/3435-hls-fix/migrated_bitmark_works_media_hosting_2026-08-25.csv`; contracts: `migrated_bitmark_contracts_2026-08-28.csv`.

Why they are CDN: the Cadence-era migration wrote CDN URLs into each token's `metadata.json`. V2 `tokenURI` = `https://ipfs.bitmark.com/ipfs/<swaps.ipfs_cid>/metadata.json`, an immutable directory — so the fix is the one already executed for On Screen Presence's 50 editions: a new directory per token and `updateArtworkEditionIPFSCid(tokenId, newCid)`.

## Goal 1 — future swaps (verify, don't build)

The current swap code already does the right thing: `internal/tasks/swap.go swapTokenToEthereum` → `swap.GenerateMetadata` reads `artwork.PreviewIPFSRef.IpfsURI` and `artwork.ThumbnailIPFSRef.IpfsURI` and **errors** (`Missing preview IPFS` / `Missing thumbnail IPFS`) rather than falling back to the CDN; the Tezos path (`GenerateTezosTokenMetadataToIPFS`) resolves the same `ipfs_reference` rows. The CDN URLs in the 5,903 predate this code.

So goal 1 reduces to: **every still-Bitmark work must have both reference rows before it is swapped.**

- Preview: done — all 4,959 `preview_uri`s have rows (215 CIDs, pinned).
- Thumbnail: **check** — their `thumbnail_uri` is an `imagedelivery.net` URL; if no `ipfs_reference` row exists the swap task fails at metadata generation (safe, but blocks the migration). Query in `ops/3435-hls-fix/db/` (`check-bitmark-thumbnail-refs.sql`); if rows are missing, run the existing `EnsureIPFSReferenceByURI` task for each distinct `thumbnail_uri` (pushes the Cloudflare image to prod-02 and writes the row — server code, not ours).
- Acceptance: the first swap after this check is inspected on Etherscan/tzkt — `animation_url` and `image` are `ipfs://`; the census then classifies it `independent`.

## Goal 2 — the 5,903 already-swapped tokens

Same procedure as `ops/3435-hls-fix/rewilded-metadata-fix` + `tools/update-token-uri`, generalised to 17 contracts.

### Step 0 — export (DB, read-only)

`ops/3435-hls-fix/db/export-v2-cdn-tokens.sql`: per token — contract, token id, artwork id, edition index, current `swaps.ipfs_cid`, `preview_uri` → its `ipfs_reference.ipfs_uri`, `thumbnail_uri` → its `ipfs_reference.ipfs_uri`. Rows where either reference is missing are listed separately: they need `EnsureIPFSReferenceByURI` first (goal 1's check, same fix).

### Step 1 — generate (local, `tools/v2-metadata-regen`, to be written from `rewilded-metadata-fix/gen.py`)

For each token: fetch `https://ipfs.bitmark.com/ipfs/<old cid>/metadata.json`, replace **only** `animation_url` (→ preview reference) and `image` (→ thumbnail reference; for image-medium series the server puts the preview in `image`, mirror that), byte-preserve everything else, write `dirs/<contract>/<tokenId>/metadata.json`, emit `plan.csv`. Diff a sample against the originals: exactly two lines change.

### Step 2 — pin (tunnel)

`pin.sh` as before (`wrap-with-directory`, CIDv0 like the originals) → `result.csv` (`contract, token_id, old_cid, new_cid`). Then `tools/pin-referenced` on the new CIDs to confirm, and a gateway HEAD of each `<new>/metadata.json` (must be 200: `ipfs.bitmark.com` is `NoFetch`).

### Step 3 — chain (`tools/update-token-uri`, per contract)

- One `config.json` per contract: `contract`, `senderAddress` (the trustee — read `trustee()` per contract; the vault-held `0xbeb9f8…492f` is expected on all 17, verify), `senderAccount`, `updates` = that contract's slice of `result.csv`.
- `preflight` per contract (on-chain `ipfsCID` must equal the csv's old value; new metadata servable; dry-run passes; uniqueness).
- Trial `run-all.mjs --limit 1` on the smallest contract (Infinite Entropy, 15), verify on Etherscan and through the gateway, then `run-all.mjs` contract by contract, smallest first, Unsupervised (4,310) last.
- Cost: ~55k gas × 5,903 ≈ 3.2×10⁸ gas; at ~1.1 gwei ≈ 0.36 ETH from the trustee. Quiet-window check on `eth_tx` before each contract (the trustee is the platform account).
- Nonces: `run-all.mjs` is strictly sequential and waits for 2 confirmations per tx; ~15 s/tx → Unsupervised alone is ~18 h. Acceptable; it resumes from `progress.json`.

### Step 4 — DB

`UPDATE swaps SET ipfs_cid = <new> WHERE contract_address = … AND token = … AND ipfs_cid = <old>` (generated like `tools/db-sql/gen-token-sql.py`). The API serves `<ipfs_cid>/metadata.json` on the next request; trigger the OpenSea refresh task per contract.

### Step 5 — measure

Census on prod-02; the 5,903 move from `dependent` to `independent`; status.feralfile.com gets an update entry. `tools/archive-probe`-style HEAD of a sample of new metadata dirs on ipfs.io.

Exit for goal 2: census `dependent` = 0 for every Bitmark-era exhibition's migrated tokens.

## Out of scope (recorded so it is not lost)

- The 17,247 CDN-dependent Ethereum works in **non-Bitmark** exhibitions (crystalline work 9,048, Unsupervised's native V2 editions are inside the 5,903 above, I KNOW 669, …): different cause (no `ipfs_reference` rows at all; V3+/V4 API-served metadata). Separate plan.
- Site / FF1 / DP-1 routing through the CDN.
- `imagedelivery.net` thumbnails as a dependency beyond what goal 1 needs.
- ff-pin-1 kubo upgrade (tracked in #3435).

## Order

```
goal 1 check (thumbnail refs) ─┐
                               ├─► step 0 export ─► step 1 generate ─► step 2 pin ─► step 3 chain (17 contracts, smallest first) ─► step 4 DB ─► step 5 census
existing tools + procedure ────┘
```
