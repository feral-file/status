# Phase-2 status — pipeline CLOSED for every platform-minted token; filum next, census deferred

*Updated 2026-09-08 (supersedes the 2026-09-04 version). Owner: Brandon.
Plan + history: `ops/cdn-retirement-phase2.md`. OpenSea incident + collection
freeze (read BEFORE touching anything OpenSea-facing):
`ops/opensea-metadata-path-incident.md`, `ops/opensea-metadata-path/README.md`.
Intermediates referenced below were removed in the 2026-09-04 repo cleanup
(`ops/repo-cleanup-2026-09-04.md`); their conclusions are recorded here, and
every input is regenerable (chain / IPFS pins / fresh DB export).*

## Where this stands in one paragraph

Every token minted through the Feral File server whose metadata media pointed
at the CDN has been repointed on chain and in the DB: V2 (5,880, goal 2), V3
(2,341) and crystalline (9,048, one `setTokenBaseURI`, **landed** — see
below). What remains on the platform-minted side is exactly the two
`alternativePreviewURI` overlays, **filum 128 + Ten Whistlegraphs 39**.
filum is next; Ten Whistlegraphs is deferred. The census rerun + status page
rebuild is deliberately held until all of it is done, so it runs once.
A new track opened on 2026-09-04 from OpenSea's audit: tokens on contracts we
deployed manually (not through the server) — their media CDN handling and how
their OpenSea `collection_uuid` gets pinned (57 collections on OpenSea's side).

## DONE — the full V3 + crystalline arc (all verified)

- **Step 0** population rebuilt: 11,517 tokens, 104 pin units; every contract
  chain-audited (V3 2,341 needs_fix = census exactly; crystalline 9,048/9,048;
  Truth 0 — its 128 census-CDN rows are the filum `alternativePreviewURI`
  overlay). Summary CSVs in `step0/`.
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
- **crystalline DB align (2026-09-04)**: 9,048/9,048 path-form UPDATEs applied
  (`tools/db-align-sql/gen-v4-sql.py`, old dir `QmY67Gq1514Zj1yWtHxoHeoVj8FpFLM5ZNSNQejjirxKTo`
  → new dir `QmNP6RC7…`). Was a DB-leads-chain exception until the tx below.
- **crystalline owner tx — LANDED.** Verified on chain 2026-09-08 by reading
  `tokenURI` on `0xBE0A4E26a156B2a60cF515E86b3Df9756DEE1952` through a public
  RPC: it returns `ipfs://QmNP6RC7…/<tokenId>`. The DB-leads-chain exception
  is closed; DB and chain agree. Broadcast was done by the owner-key holder
  per `RUNBOOK-crystalline-base-uri.md`; the tx hash is not recorded here
  (the chain is the receipt — look up the contract's latest owner tx if it is
  ever needed).

## NOT DONE — in order

1. **filum (Truth `0xBb12686c360e9057be3CD031140035A705e19ceC`, 128 tokens)
   — CLOSED 2026-09-08.** Owner tx landed: `tokenURI` on chain now returns
   `ipfs://QmZTedFYmyhEH7G77BTnuVk7DHrYWJzdHaWK4wMeXwkPVo/<id>` (verified
   2026-09-08 by direct read; smoke-tested end to end through the chain-sourced
   census path: image + animation `ipfs://`, all gateways ok). DB `ipfs_cid`
   aligned (896 × UPDATE 1) the same day; the `alternativePreviewURI` overlay
   stays by decision (chain alignment, not feralfile.com display). Full record:
   `filum/README.md`. **Every platform-minted token whose tokenURI doc pointed
   at the CDN is now repointed on chain.**
2. **Ten Whistlegraphs (`0x9294c5…`, 39 tokens) — DEFERRED.** Overlay to
   aesthetic.computer (third-party by choice). Decision pending with
   Sean/Hieu; nothing to run. Status page reclassification only.
3. **HARD RULE, narrowed 2026-09-04: no OpenSea metadata refresh for the 17
   unbound special-project collections** (Ryan: on hold, refreshes paused
   there). Everything platform-minted is frozen and bound on OpenSea's side;
   the resume/pause split from Ryan's mail stands. Still: do not dispatch a
   platform-wide refresh without checking `ops/opensea-metadata-path/README.md`
   first.
4. **Special-project class (contracts deployed manually from our address,
   not through the server) — media MEASURED 2026-09-08**
   (`ops/special-project-contracts/README.md`). Population = the 103 contracts
   created by the deployer `0x1d05cf6c…` (Blockscout): 45 platform, 18
   helpers/tests, **40 NFT contracts / 1,588 tokens outside every census and
   tool**. The 38 real special projects (1,335 tokens: a2p, Machine
   Hallucinations, Aorist-era, 2024-25 drops) are **100% `ipfs://` on chain
   and all 368 media CIDs are on prod-02** — nothing to repoint; 367 of them
   were cache-only and were given recursive pins 2026-09-08 (ff-deploy#28
   policy). The
   CDN dependency is **200 tokens on two superseded deployments** —
   `0x22e130a4…` (first Peer to Peer contract, replaced by `0x2A86…` five
   days later; 204/251 in the FF vault, 47 in 15 outside wallets) and
   `0xc764a826…` (pre-V2 007 contract, 2 tokens, both in the deployer
   wallet). **Decided 2026-09-08: out of scope** (official counterparts are
   already covered); fix recipe kept in the README if the 47 ever matter. Side
   findings: the indexer does not index 30 of the 40 (registry gap, issue to
   file); the census cannot take a contract list (issue to file).
   (b) **collection_uuid pinning** for the 38: per-token uuid5 of
   `collection_name` → one stored value per collection, server-side; every
   token's `collection_name` is now on record; design + the 57-row mapping
   for Ryan (promised week of 2026-09-07) still open.
5. **Close-out measurement — census 2026-09-08 RUN, close-out in progress.**
   `token_census_20260908T051950Z.csv` (34,987 tokens scanned, 5 h; +21
   contract-held Tezos works appended via rescan mode A → 35,008). Two
   defects in the checker surfaced and were fixed upstream
   (feral-file/agentic-workflows#52 + ff-deploy#34, not yet deployed):
   (a) 24,606 ipfs.io / 24,696 dweb.link probes came back HTTP 429 at
   4 req/s/host with 429 excluded from retries → paced re-probe running
   (2,477 distinct CIDs; all pass so far); (b) Ethereum metadata was read from
   feralfile.com/api, so filum's overlay still shows 128 CDN rows although
   the chain is clean → census now reads `tokenURI` on chain. Expected page
   numbers from this CSV: `depend entirely on Feral File` 0 (build.py counts
   a work dependent only when it has NO content-addressed file; filum's
   thumbnails are IPFS), gateway-gap 0 after the re-probe, third-party 0.
   Data lands on this branch (PR #11); CI builds the page.
6. **#3435 checkpoint comment** — everything since 9/3 is unreported (V3 DB
   align + reference rows + explicit pins, crystalline tx landed, OpenSea
   freeze + Ryan's audit, filum-first ordering). Post it with the census
   numbers, or before if the wait for 1 stretches.
7. **Unpin backlog** — only after the census confirms nothing references
   them; re-derive the reference set first. Candidates: superseded HLS dirs,
   old V2 metadata dirs, old V3 doc CIDs (old halves of `step3/updates_0x*.csv`),
   crystalline old dir `QmY67Gq1…`, the 6 V3 staging roots
   (`step3/staging_roots.csv`).

## Parallel / pending (not blocking)

- **OpenSea (Ryan thread), state 2026-09-04**: Infinite Entropy FIXED (bound
  to `71513905-…`, 24/24 tokens back in the verified collection, duplicate
  empty); five collections bound (IE, Study for Unsupervised, MONOPOLY SET,
  Peer to Peer Launch Party Exclusive, Inaugural SuperBridge Summit); 198
  tokens moved from exhibition-level groupings into their series (36 Points,
  Venuses included). Total 410 FF collections on their side, breakdown in
  `ops/opensea-metadata-path/README.md`. Background item-delists (11 untouched
  tokens on 6 contracts, ~4-5% control rate): separate sweep + appeal track,
  report `opensea_delist_report.csv`.
- **Scheduled archive-probe** (Sean's two independent checks: real child
  bytes through a public gateway + ff-pin-1 itself listed as provider for
  every manifest root; both nodes on kubo 0.43). Not yet scheduled; ff-deploy
  has no job for it. ff-pin-1 pre-upgrade DO snapshot is past its
  ~2026-09-05 keep date — delete.
- **agentic-workflows**: upstream regression for the 21 contract-held Tezos
  works (census refetch still drops them after #50; rescan mode A is the
  workaround). Not filed yet.
- **Manifest v2 `setManifest`** (#3502, Sean + Safe signers): still open,
  live page `archive_registry.version` = 1.
- **nonipfs-scan (closed)**: status PR #10; the 5 Art of Survival thumbnail
  403s were fixed at origin 2026-09-02 and verified.
- **Open PRs**: status #10 (nonipfs-scan), #11 (this branch,
  tools/phase2-step0) — merge.

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
  Since 2026-09-04 both fields are stored explicitly on every ETH series
  (`ops/opensea-metadata-path/freeze_collection_fields.sql`); new series
  still need a server-side guard so they don't fall back to derivation.
- `artworks.metadata.ipfs_cid`: V4 = PATH `<dirCID>/<tokenId>`; V3 = bare CID
  (confirmed 2026-09-04); V2 uses `swaps.ipfs_cid`.
- The CDN rewrites `generated_images/<name>?variant=<v>` →
  `generated_images/<v>/<name>` (folded into the crystalline regen).
- V3 has no `trustee()` getter — authorization proven via per-token eth_call
  dry-runs; sender was `0xbeb9f810…` (same vault key as goal-2). V4/V4_2
  `setTokenBaseURI` is **onlyOwner** (owner `0x1d05cf6c…`, key held by a
  teammate, not the platform trustee key). Truth (filum) is the same shape.
- kubo API: pin/add streams errors after the 200 header (check for `"Pins"`
  in the body); prefer batched pin/add (multiple `arg`s per call — 2,341
  one-by-one calls froze; `tools/pin-referenced/batch_pin.py`); big uploads
  go per-file/batched into MFS, never one giant POST; `sort | head -1` under
  pipefail dies on SIGPIPE for big lists.
- Public RPCs: most are DNS-blocked or rate-limited on this network — use
  Infura; `1rpc.io/eth` worked for a read on 2026-09-08. Etag parsing: strip
  `W/` prefix then quotes only (`.strip('"W/')` eats trailing W's).
- psql discipline: generators emit `BEGIN;` without `COMMIT` — first run with
  `-f` is a free dry-run (rollback on disconnect), append `COMMIT` to apply.
