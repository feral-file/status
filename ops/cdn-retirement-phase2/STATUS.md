# Phase-2 status — V3 arc CLOSED end-to-end; census close-out + crystalline tx remain

*Updated 2026-09-04 (supersedes HANDOFF-2026-09-04.md). Owner: Brandon.
Plan + history: `ops/cdn-retirement-phase2.md`. OpenSea incident (read BEFORE
touching anything OpenSea-facing): `ops/opensea-metadata-path-incident.md`.
Intermediates referenced below were removed in the 2026-09-04 repo cleanup
(`ops/repo-cleanup-2026-09-04.md`); their conclusions are recorded here, and
every input is regenerable (chain / IPFS pins / fresh DB export).*

## DONE — the full V3 arc (all verified)

- **Step 0** population rebuilt: 11,517 tokens, 104 pin units; every contract
  chain-audited (V3 2,341 needs_fix = census exactly; crystalline 9,048/9,048;
  Truth 0 — its 128 census-CDN rows are the filum `alternativePreviewURI`
  overlay, out of scope). Summary CSVs in `step0/`.
- **Step 1** all 104 CDN units (40.2 GB, 74k files) mirrored and pinned on
  prod-02, ff-gateway byte-verified — registry: `step1/dir_cids.csv`
  (104/104 verified=yes). prod-02 ~727 GB of 900 GB.
- **Step 3 regen** V3 2,341 docs + crystalline 9,048 docs, byte-preserving,
  only media keys changed — independently verified (`step3/VERIFICATION.md`).
  All new docs pinned (staging roots in `step3/staging_roots.csv`; crystalline
  new dir `QmNP6RC7Z5DRV8sQsmRgssQS3GP77BUCAK2UV4q94WfiMv`).
- **V3 chain rollout (2026-09-03)**: 2,341/2,341 `updateArtworkEditionIPFSCid`
  txs confirmed across six contracts, per-contract full check green
  (Material Wonderland 108, Gray Matter 171, BOOM TOWN 182, Chain Reaction
  600, Peer to Peer 611, I KNOW 669). The chain is the receipt.
- **V3 DB align (2026-09-04)**: `artworks.metadata.ipfs_cid` = bare CID on V3
  (form confirmed from export). 2,341/2,341 UPDATEs applied, WHERE-pinned to
  the old value + series_id (generator: `tools/db-align-sql/gen-v3-sql.py`,
  mapping: `step3/updates_0x*.csv`). Pre-flight spot-check: 60 series × 2
  tokens = 117 docs, 224 media pairs CDN-vs-IPFS byte-identical (first 64KB +
  length), doc diffs limited to `image`/`animation_url`; 8 series store the
  old image as a RELATIVE `previews/…` path (known residual class, verified
  equivalent).
- **Reference rows (2026-09-04)**: +18,096 `ipfs_reference` upserts
  (`tools/db-align-sql/gen-reference-sql.py`). Review outcomes:
  - 1,857 conflict rows benign — existing file-CID target byte-identical to
    the computed dir+path target (all 144 unique pairs verified); left alone.
  - **182 rows fixed** — existing target was a dir CID with no root
    `index.html` (gateway served a directory listing, not the artwork; all on
    BOOM TOWN, 8 series dirs). Fix record: `step2/reference-fix-dirlisting.sql`.
  - 1,632 unmapped rows need nothing: 1,544 already had an ipfs ref (not in
    CDN pin-unit scope); 88 are `imagedelivery.net` (third-party, out of
    scope, see `step0/third_party.csv`).
- **pin-referenced rerun (2026-09-04)**: fresh referenced set = 120,563 refs
  → 76,448 unique root CIDs. **All present on prod-02, 0 missing**; the 2,341
  present-but-unpinned were exactly the new V3 docs (previously covered only
  by the 6 staging-root pins) — all given direct pins via
  `tools/pin-referenced/batch_pin.py`. Referenced set is now 100% explicitly
  pinned; staging roots decoupled and unpinnable later.
- **crystalline DB align (2026-09-04, deliberate DB-leads-chain exception)**:
  9,048/9,048 path-form UPDATEs applied
  (`tools/db-align-sql/gen-v4-sql.py`, old dir `QmY67Gq1514Zj1yWtHxoHeoVj8FpFLM5ZNSNQejjirxKTo`
  → new dir `QmNP6RC7…`). **The DB leads the chain until the owner tx lands**;
  if the tx is ever abandoned, revert by regenerating with the dirs swapped.

## NOT DONE — in order

1. **HARD RULE unchanged: no OpenSea metadata refresh** for V3 or crystalline
   until OpenSea confirms the metadata-path fix (refresh is the known
   re-bucketing trigger). Delist monitoring is on OpenSea's side (Ryan
   thread); `tools/opensea/delist-scan.py` remains for spot-checks.
2. **crystalline owner tx** — with the key-holding teammate:
   `RUNBOOK-crystalline-base-uri.md` (one `setTokenBaseURI` tx; config
   example prefilled; `tools/update-token-uri/v4-base-uri.mjs`). DB side is
   already done (see above) — after the tx lands, nothing further.
3. **Close-out measurement**: census on prod-02 → `census-rescan` → status
   page rebuild → `census/<date>` branch → PR. Target: ETH `dependent` drops
   11,389 → ~167 (overlay-only: filum 128 + Ten Whistlegraphs 39).
4. **#3435 checkpoint comment** — everything since 9/1 is unreported (V3
   completion + DB/reference/pin close-out + OpenSea incident); write it once
   census numbers are in.
5. **Unpin backlog** — only after the census confirms nothing references
   them; re-derive the reference set first. Candidates: superseded HLS dirs,
   old V2 metadata dirs, old V3 doc CIDs (old halves of `step3/updates_0x*.csv`),
   crystalline old dir `QmY67Gq1…`, the 6 V3 staging roots
   (`step3/staging_roots.csv`).

## Parallel / pending (not blocking)

- **OpenSea/Ryan thread**: restore IE's 15 tokens, remove duplicate
  collection, per-collection metadata-source list; confirm bypass from FF API
  access logs (prod-01, refresh window 2026-09-01). Background item-delists:
  11 untouched tokens on 6 contracts (~4-5% control rate), separate sweep +
  appeal track. Report: `opensea_delist_report.csv`.
- **Overlay/product decisions**: filum 128 (7-attribute crossorigin patch
  would make the IPFS version whole — needs artist sign-off) + Ten
  Whistlegraphs 39. See `ops/cdn-retirement-phase2.md` § Pending decisions.
- **Scheduled archive-probe** (Sean's two independent checks; both nodes on
  kubo 0.43); ff-pin-1 pre-upgrade DO snapshot deletable after ~2026-09-05.
- **agentic-workflows**: upstream issue for the 21 contract-held Tezos works
  (census refetch drops them; rescan mode A is the workaround).
- **nonipfs-scan (closed)**: status PR #10; the 5 Art of Survival thumbnail
  403s were fixed at origin 2026-09-02 and verified.

## goal-2 / V2 rollout receipts (2026-09-01..03)

23 contracts completed via `tools/metadata-regen` + `tools/update-token-uri`
(runs/ logs deleted in cleanup; the chain is the receipt):

```
0x9294c5787f5bc7462e991fe8b6feac75f433ac39  0x0a5c44da5f71b884c16a195cec304f47ac0233cf
0x7a9ea7c036f6aab113e2563096ef1e0e56375a39  0x63c8282c8705e7873b3302bd623b2bc8ebcdddd3
0x1d5bdc75918600541c115b74b81a404c9e4af7d4  0x513ac47320798fb6d74543242a9c0f686682998d
0xadb387798599f5777cd0531c2ecb36007c1d1a51  0x6e906b2e355294a6aecd6b4f75816eda9f703dda
0xe5163c74ffe6563d75d750e5d767122500a1c337  0xdb5f1adcffa1869b9711cbfbe3bf46cc5d5319e5
0x29c9e04e05c5d261836e458bc5b779a7de3c58d6  0x6dba130221a1c39f6623908a136976686050059a
0x979316f5b3f3d8db956af519553c853525a5b1af  0xaa02cc02f4531ee75d1b78cb5a155d4f3b54f830
0xd8eed224e1b358fa6f7b167124c2c1afe42275b4  0x28b51ba8b990c48cb22cb6ef0ad5415fdba5210c
0x7a15b36cb834aea88553de69077d3777460d73ac  0x8f30722dd16bd63cf2665c383c1aef5e307b0046
0x6e82e4b398ca4137007ba69ddd6ff699334d13b5  0x6003994adeca13407e8dbee808280cc3ef2ab820
0xc4f0ee96676d3de800b9725eb628de1c5a0cbea1  0x2a86c5466f088caebf94e071a77669bae371cd87
0xe46a41b840176b62983fc71162dc9faeac4d9bcb
```

## Gotchas (kept from the handoff so nobody relearns them)

- OpenSea per-token metadata source varies (FF API vs direct tokenURI) —
  grouping comes from API-injected collection_name/uuid; direct reads lose it.
- `artworks.metadata.ipfs_cid`: V4 = PATH `<dirCID>/<tokenId>`; V3 = bare CID
  (confirmed 2026-09-04); V2 uses `swaps.ipfs_cid`.
- The CDN rewrites `generated_images/<name>?variant=<v>` →
  `generated_images/<v>/<name>` (folded into the crystalline regen).
- V3 has no `trustee()` getter — authorization proven via per-token eth_call
  dry-runs; sender was `0xbeb9f810…` (same vault key as goal-2). V4/V4_2
  `setTokenBaseURI` is **onlyOwner** (owner `0x1d05cf6c…`, key held by a
  teammate, not the platform trustee key).
- kubo API: pin/add streams errors after the 200 header (check for `"Pins"`
  in the body); prefer batched pin/add (multiple `arg`s per call — 2,341
  one-by-one calls froze; `tools/pin-referenced/batch_pin.py`); big uploads
  go per-file/batched into MFS, never one giant POST; `sort | head -1` under
  pipefail dies on SIGPIPE for big lists.
- Public RPCs are DNS-blocked on this network — use Infura; Etag parsing:
  strip `W/` prefix then quotes only (`.strip('"W/')` eats trailing W's).
- psql discipline: generators emit `BEGIN;` without `COMMIT` — first run with
  `-f` is a free dry-run (rollback on disconnect), append `COMMIT` to apply.
