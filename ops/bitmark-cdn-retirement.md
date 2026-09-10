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

## Spot check of the classification (2026-08-28, 7 tokens, on-chain via `tokenURI` → `metadata.json`)

| Census class | Token | On-chain `animation_url` / `image` | Verdict |
|---|---|---|---|
| cdn | Unsupervised …12551783 | `cdn.feralfileassets.com/previews/…` / `cdn…/thumbnails/…` | confirmed |
| cdn | On Screen Presence …06566827 | CDN / CDN | confirmed |
| cdn | Primordium …35090312 | CDN / `imagedelivery.net/…` | confirmed (image is Cloudflare Images, also non-IPFS) |
| all-ipfs | For Your Eyes Only …78215162 | `ipfs://Qmc47A…` / `ipfs://QmTUus…` | confirmed |
| all-ipfs | The Bardo …77500370 | `ipfs://QmbTnb…?edition_number=200&…` / `ipfs://QmXESF…` | confirmed |
| other:cid,other | Ten Whistlegraphs …65013560 | **`ipfs://QmWkJw…?edition_number=3…`** / `ipfs://QmUH8J…` | **census wrong**: the API applied `metadata.alternativePreviewURI` (`aesthetic.computer`); chain is IPFS |
| other:other | Instructions Follow …23053778 | none / `imagedelivery.net/…` | image-medium work, `image` on Cloudflare Images — non-IPFS, must be fixed too |

Lesson: for Ethereum V2 the census reads `GET /api/contracts/…` — which serves the token's `metadata.json` from IPFS but then overlays `alternativePreviewURI` and rewrites `ipfs://` to the gateway. It is right about CDN-vs-IPFS in the common case but not authoritative. **The fix list must be built from the chain**: `tokenURI(tokenId)` → fetch → classify `animation_url` and `image` (rule: fixed if either is not `ipfs://`). `imagedelivery.net` images count as non-IPFS.

### Verification for the next agent, before generating anything

1. For every migrated Ethereum token of a Bitmark-era exhibition (the 11,537 in `migrated_bitmark_works_media_hosting_2026-08-25.csv`, or the export from step 0), read `tokenURI` on-chain (batch `eth_call`s through a paid RPC — public ones rate-limit and this network DNS-blocks several), fetch `metadata.json` from `ipfs.bitmark.com`, and record `animation_url`, `image`, and the directory CID actually on chain.
2. Compare with `swaps.ipfs_cid` from the DB export: any mismatch means the DB is behind the chain (or vice versa) and that token goes on a separate list.
3. The corrected fix list replaces the census-derived 5,903. Expect it to be close but not identical (the `other` classes will shrink; `imagedelivery.net` images will add some).

## Goal 1 — future swaps (verify, don't build)

The current swap code already does the right thing: `internal/tasks/swap.go swapTokenToEthereum` → `swap.GenerateMetadata` reads `artwork.PreviewIPFSRef.IpfsURI` and `artwork.ThumbnailIPFSRef.IpfsURI` and **errors** (`Missing preview IPFS` / `Missing thumbnail IPFS`) rather than falling back to the CDN; the Tezos path (`GenerateTezosTokenMetadataToIPFS`) resolves the same `ipfs_reference` rows. The CDN URLs in the 5,903 predate this code.

So goal 1 reduces to: **every still-Bitmark work must have both reference rows before it is swapped.**

- Preview: done — all 4,959 `preview_uri`s have rows (215 CIDs, pinned).
- Thumbnail: **checked 2026-08-28** (`ops/3435-hls-fix/db/check-bitmark-thumbnail-refs.sql`): works 4,959, missing preview refs 0, missing thumbnail refs 0. Nothing to push.
- Acceptance: the first swap after this check is inspected on Etherscan/tzkt — `animation_url` and `image` are `ipfs://`; the census then classifies it `independent`.

## Goal 2 — the 5,903 already-swapped tokens — **DONE 2026-09-01** (5,880 tokens after chain-side audit; execution record: `ops/bitmark-cdn-retirement/SUMMARY.md`)

Same procedure as `ops/3435-hls-fix/rewilded-metadata-fix` + `tools/update-token-uri`, generalised to 17 contracts.

### Step 0 — export (DB, read-only)

`ops/3435-hls-fix/db/export-v2-cdn-tokens.sql`: per token — contract, token id, artwork id, edition index, current `swaps.ipfs_cid`, `preview_uri` → its `ipfs_reference.ipfs_uri`, `thumbnail_uri` → its `ipfs_reference.ipfs_uri`. Rows where either reference is missing are listed separately: they need `EnsureIPFSReferenceByURI` first (goal 1's check, same fix).

### Step 1 — generate (local, `tools/metadata-regen` — written 2026-08-28, see its README; `audit.py` there is the chain-side verification above)

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

`UPDATE swaps SET ipfs_cid = <new> WHERE contract_address = … AND token = … AND ipfs_cid = <old>` (generated like `tools/db-align-sql/gen-token-sql.py`). The API serves `<ipfs_cid>/metadata.json` on the next request; trigger the OpenSea refresh task per contract.

### Step 5 — measure

Census on prod-02; the 5,903 move from `dependent` to `independent`; status.feralfile.com gets an update entry. `tools/archive-probe`-style HEAD of a sample of new metadata dirs on ipfs.io.

Exit for goal 2: census `dependent` = 0 for every Bitmark-era exhibition's migrated tokens.

Decisions taken 2026-08-28: the DB export (step 0) is **not** run yet — next agent starts there. Tooling for steps 1–4 exists in `tools/metadata-regen/`; **audit + generate + media verification ran 2026-08-28: the chain-built fix list is 5,880 tokens (not 5,903), 0 blocked, all 436 media CIDs publicly fetchable — see the run record in that README; pin/chain/DB not started** (audit → gen → verify-media → pin → per-contract update-token-uri configs → SQL); `run-all.mjs` now takes a per-config `workDir` so 17 contracts never share `progress.json`. The contract holds only the directory CID (verified from source): `?edition_number=…` parameters are plain metadata values, and `gen.py` refuses any rewrite that drops or changes them. `image` rule: use the thumbnail's `ipfs_reference` CID (the On Screen Presence procedure); if a series' thumbnail reference is missing, run `EnsureIPFSReferenceByURI` first — never leave a CDN or `imagedelivery.net` URL in regenerated metadata.

## Out of scope (recorded so it is not lost)

- ➜ now planned: `ops/cdn-retirement-phase2.md` (2026-09-01). The CDN-dependent Ethereum works in **non-Bitmark** exhibitions — **11,517** (census 8/25; the 17,247 previously written here mislabeled the ALL-ETH fully-CDN total of ~17.25k, which double-counts this plan's own ~5.9k migrated Bitmark-era tokens; reconciliation in the phase-2 doc) — crystalline work 9,048, I KNOW 669, …: different cause (no `ipfs_reference` rows at all; V3+/V4 API-served metadata). Separate plan.
- Site / FF1 / DP-1 routing through the CDN.
- `imagedelivery.net` thumbnails as a dependency beyond what goal 1 needs.
- ff-pin-1 kubo upgrade (tracked in #3435).

## Order

```
goal 1 check (thumbnail refs) ─┐
                               ├─► step 0 export ─► step 1 generate ─► step 2 pin ─► step 3 chain (17 contracts, smallest first) ─► step 4 DB ─► step 5 census
existing tools + procedure ────┘
```

## Context for the next agent — what has been done and where things stand (2026-08-28)

Thread: feral-file/feral-file#3435. Everything below is on `feral-file/status` branch `tools/step2-archive-mirror` (PR #4, pending merge) unless noted.

**Done, verified**
- 184 "gateway-gap" works (3 HLS playlists): MP4s pinned; 50 ETH editions re-pointed via `updateArtworkEditionIPFSCid`, 142 Tezos via `update_edition_metadata`; DB updated. Census 8/25: gateway-gap 184 → 0. Tools: `tools/update-token-uri` (ETH V2, vault-signed), `tools/update-tezos-metadata` (FA2, vault-signed), `tools/db-align-sql/gen-token-sql.py`; records in `ops/3435-hls-fix/`.
- prod-02 (`ipfs.feralfile.com` = `ipfs.bitmark.com`, kubo 0.39): volume 1000 GB / StorageMax 900 GB (ff-deploy#27 merged); all 215 Bitmark-era series mirrored from ff-pin-1 (verify 215/215); every DB-referenced (73,385) and chain-referenced (198) CID pinned — they had been unpinned cache, alive only because the container runs without `--enable-gc` (ff-deploy#28, docs, pending merge). 74,311 recursive pins. Sweep provider announces everything.
- ff-pin-1 (custody node, Sean's box, Brandon co-operator via DO console; Canon `ops/archival-node.md` is the contract and the change log): kubo 0.32.1, `Reprovider.Strategy=roots`, ConnMgr 100/250, `/root/provide-roots.sh` (retry ×3) on cron 03:00 UTC announces the ~230 roots because 0.32's reprovider never completes. Archive probe: ipfs.io 228/230. Planned: upgrade to kubo 0.39, then `Strategy=all`, retire the loop. Not scheduled.
- `ipfs_reference` cleanup: 157 rows rebuilt, 9 truncated orphans deleted (`ops/3435-hls-fix/db/`).
- Bitmark-era reference layer: all 4,959 not-yet-migrated works have preview and thumbnail `ipfs_reference` rows; the 215 preview CIDs are pinned and resolve on our gateway and ipfs.io.

**Pending merges** (all reviewed by Brandon, awaiting his click): status PR #3 (census retry), PR #4 (this branch), ff-deploy PR #28 (docs).

**Open**
- This plan's goal 2 (5,903-ish tokens) — start with the chain-side verification above, then step 0.
- Unpin superseded HLS metadata on prod-02 (50 ETH dirs, 142 Tezos JSONs, 3 playlists) once nothing references them.
- ff-pin-1 kubo upgrade; scheduled archive probe (tool exists, not scheduled).
- agentic-workflows #47 (monitor skips contract-held tokens) and #48 (retry a single failed gateway probe).
- Out of scope but recorded: 17,247 CDN-dependent ETH works in non-Bitmark exhibitions (no `ipfs_reference` rows; V3+/V4 API-served metadata).

**How to work on prod-02**: `make ipfs-port-forward ENV=prod HOST=prod-02` in ff-deploy (kubo API at 127.0.0.1:5001, gateway 8080); `make ssh ENV=prod HOST=prod-02` for the host. Never run `ipfs repo gc` there. Public RPCs from this network: `https://1rpc.io/eth` works via curl; `publicnode.com`/`flashbots.net` are DNS-blocked by the router; Python `urllib` hits cert mismatches for the same reason — use curl or a paid RPC.
