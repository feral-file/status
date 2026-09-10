# Phase-2 status — pipeline CLOSED for every platform-minted token; close-out census PUBLISHED 2026-09-09 (CDN-dependent works 11,389 → 0)

*Updated 2026-09-10 (supersedes the 2026-09-08 version). Owner: Brandon.
Plan + history: `ops/cdn-retirement-phase2.md`. OpenSea incident + collection
freeze (read BEFORE touching anything OpenSea-facing):
`ops/opensea-metadata-path-incident.md`, `ops/opensea-metadata-path/README.md`.
Intermediates referenced below were removed in the 2026-09-04 repo cleanup
(`ops/repo-cleanup.md`); their conclusions are recorded here, and
every input is regenerable (chain / IPFS pins / fresh DB export).*

## Where this stands in one paragraph

Every token minted through the Feral File server whose metadata media pointed
at the CDN has been repointed on chain and in the DB: V2 (5,880, goal 2), V3
(2,341) and crystalline (9,048, one `setTokenBaseURI`, **landed** — see
below) and filum / Truth (896, one `setTokenBaseURI`, **landed 2026-09-08**,
item 1 below). Nothing platform-minted is left to repoint. The two
`alternativePreviewURI` overlays remain by decision: filum's 128 (kept — chain
alignment, not feralfile.com display) and Ten Whistlegraphs' 39 (deferred,
third-party by choice). The close-out census ran once, 2026-09-09, and is
published (item 5).
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
5. **Close-out measurement — DONE, published 2026-09-09/10.** The tiered
   census (`token_census_20260909T100006Z.csv`, image `f6367b7`, 14.6 h,
   summary `census_summary_2026-09-09.md`): 34,923 works / 106,116 files,
   Filebase primary served 70,987 of 70,988 IPFS rows (1 via Pinata), 0 fail,
   0 unmeasured, no circuit; verdicts redundant 49,019 / independent 21,975 /
   ff_only 0. Page: `depend on our CDN` 11,389 → **0**, redundant 22,596,
   independent 12,327. 288 cold CIDs were deferred and retried (287 resolved
   on Filebase). Four hand corrections to the raw CSV before publishing —
   64 burned CRAWL tokens dropped from the population, CRAWL `…764` (base
   URI predates the token) measured by hand, FYEO #96 (hex token id in DB)
   and Bardo #174 (one RPC transport error) measured by hand — are recorded
   with evidence in `census-2026-09-09/README.md`; they spawn items 8–10.
   Phase-3 populations measured by the run: 14,591 ETH tokenURIs through
   `ipfs.bitmark.com`, 199 media rows on FF gateway URLs (same README).
   History of the defective 9/8 run, kept for the record: the v1 run
   (`token_census_20260908T051950Z.csv`, 34,987 tokens, 5 h; summary in
   `census_summary_2026-09-08.md`) produced 24,606 ipfs.io + 24,696 dweb.link
   HTTP 429s (one Cloudflare quota shared by both gateways, refilling on a
   ~10–20 min cycle; a 1 req/s re-probe still failed in waves) and counted
   filum as CDN-hosted from the feralfile.com API's display overlay although
   the chain was already clean. **That CSV is NOT committed** — `build.py`
   picks the newest census and would have published 14,300 throttled works as
   gateway gaps; it stays on Brandon's machine as a record of the defect.
   Fixed upstream, all merged 2026-09-08: agentic-workflows#52 (Ethereum
   metadata read from `tokenURI` on chain; 429 = cooldown + adaptive spacing +
   bounded retry), agentic-workflows#54 (census schema 2: per-CID verdict from
   our gateway + one non-FF public gateway rotated by operator + delegated-
   routing providers with our peer IDs subtracted → `redundant` /
   `independent` / `ff_only` / `unreachable` / `unmeasured`; CID-level
   measurement), status#13 (page reads schema 2: "resolve without us" split
   into redundant vs only-copy-ours, `ff_only` folded into "depends on us",
   `unmeasured` shown as its own state, `rescan-cids.py`). Plan:
   `agentic-workflows/token-health-monitor/docs/plan-artwork-independence-probe.md`.
   **Remaining to publish (updated 2026-09-09):** (a)–(c) of the original
   list are done (ff-deploy#34–#40 merged, image `a2686ed` deployed) — but
   the v2 census through the public gateways alone ran at ~530 requests/hour
   from prod-02 (Shipyard/Pinata quotas) and is superseded: the publishing
   run is the **tiered census** (agentic-workflows
   `token-health-monitor/docs/plan-tiered-gateway-pool.md`: a dedicated
   Filebase gateway as the primary source, public gateways as backups, ≈2 h
   per census). Steps: agentic-workflows refactor + tiered PRs merged → image
   built → ff-deploy tiered-pool PR (vault `token_health_gateway_auth_filebase`,
   host_vars primary) deployed → census → (d) unchanged: commit the CSV to
   `data/census/` on this branch — CI builds the page. This branch already
   carries the page copy for it ("a gateway we do not operate", Filebase
   named in the method, `public_via` in the lookup).
   Expected: `depend entirely on Feral File` = CDN-only 0 + `ff_only` = the
   content only we announce (a real number the page has never shown);
   `unmeasured` small and listed. **Outcome 2026-09-09: CDN-only 0, ff_only
   0, unmeasured 0.**
6. **#3435 checkpoint comment — POSTED 2026-09-10**
   (feral-file/feral-file#3435, comment `issuecomment-5611733862`): crystalline
   + filum landed, special-project class, OpenSea state, checker rebuild, the
   2026-09-09 census numbers, the four corrections, remaining items.
7. **Unpin backlog** — only after the census confirms nothing references
   them; re-derive the reference set first. Candidates: superseded HLS dirs,
   old V2 metadata dirs, old V3 doc CIDs (old halves of `step3/updates_0x*.csv`),
   crystalline old dir `QmY67Gq1…`, the 6 V3 staging roots
   (`step3/staging_roots.csv`).
8. **CRAWL base URI — owner tx requested from Hieu 2026-09-10.** Contract
   `0x81c882c59799eA442317D020c39174AaAa8d7FC7` (FeralfileExhibitionV4_3,
   owner `0x1d05cf6c…`): `setTokenBaseURI("ipfs://QmfK7MjgYTwyAuRWCS44WzGNFzCd3y2Msu1BeJp1VqwJ47")`
   (no trailing slash, same form as the stored `ipfs://QmXfp5…`). Why: the
   server regenerated the 543-doc directory on 2026-07-02 when it finally
   created the artwork for the 2025-08-16 merge token `…764`, but the chain
   still names the 2024-09-04 directory (542 docs) set on 2026-02-02 — that
   token's `tokenURI` 404s and the DB has led the chain for the whole contract
   since July. The new dir also changes the platform royalty address
   (`0x2033…` → `0x080F…`) and paragraph markup in all 542 other docs
   (full diff + timeline: `census-2026-09-09/README.md`). Verify after:
   `tokenURI(…764)` resolves on ipfs.feralfile.com. No OpenSea refresh (item 3).
9. **FYEO #96 DB align — SQL ready, not applied.**
   `census-2026-09-09/fyeo-96-swap-token-align.sql`: `swaps.token` and the
   artwork token id hold the Bitmark 64-hex id; every sibling holds the
   decimal uint256 (the on-chain id is the hex read as uint256, verified via
   `ownerOf`/`tokenURI`). Two `UPDATE … WHERE`-pinned statements; dry-run
   without COMMIT first (expect `UPDATE 1` twice).
10. **Checker + API follow-ups from the 67 unreadable tokens** (to file in
    agentic-workflows / feral-file-server): (a) exclude API artworks whose
    `ownerAddress` is the zero address from the census universe and report
    the count — 64 CRAWL tokens burned in merges are listed by the API as
    settled artworks; a `tokenURI` revert stays a metadata error for anything
    else; (b) accept a 64-hex token id without `0x`; (c) retry an RPC
    transport error once. API side: a burned flag on artworks so census,
    indexer and status stop guessing. Also seen: ipfs.io answered its only
    request of the run with 429 `Retry-After: 900` — from prod-02 Shipyard is
    effectively closed, Pinata answers.

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
