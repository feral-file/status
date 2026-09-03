# OpenSea metadata-path incident — refresh bypassed the Feral File API, tokens re-bucketed into an auto-generated duplicate collection, duplicate delisted

*Written 2026-09-04 for the next agent. Owner: Brandon. Self-contained — no prior
conversation context needed. Tracks feral-file/feral-file#3435 (phase-2 rollout is
PAUSED on this incident). An email describing it has been sent to Ryan at OpenSea
(subject: "Feral File: collection delisted after metadata refresh — request for help").*

## The problem in one paragraph

As part of the CDN-retirement work, 5,880 FeralfileExhibitionV2 tokens got new
on-chain metadata (media keys repointed from `cdn.feralfileassets.com` to `ipfs://…`,
everything else byte-preserved) followed by an OpenSea metadata refresh
(back-office `refreshOpenSeaTokensMetadata`, dispatched 2026-09-01). For exactly one
collection — **Infinite Entropy by Rafaël Rozendaal**, contract
`0x0a5c44da5f71b884c16a195cec304f47ac0233cf`, 24 tokens, 15 of them in the fix set —
the refresh appears to have read metadata **directly from tokenURI** instead of
through the Feral File API. The on-chain docs carry no `collection_name`/
`collection_uuid` (those are API-injected), so OpenSea re-bucketed the 15 refreshed
tokens out of the verified collection into an **auto-generated duplicate collection**
with the same display name (slug `infinite-entropy-by-rafael-rozendaal-447173843`),
and that duplicate was then **delisted for a "suspected Terms of Service violation"**
— almost certainly same-name fake-collection detection.

## Verified facts (each independently checkable)

1. **Grouping on OpenSea is series-level, not contract-level.** FF collections on
   OpenSea ("filum by Ella Hoeppner", "peep-o-rama by Carla Gannis", "Infinite
   Entropy by Rafaël Rozendaal") correspond to SERIES, while on-chain contracts are
   exhibition-level (one V2 contract per exhibition, many series). The only source
   for series grouping is the `collection_name` + `collection_uuid` the FF API
   injects (`feral-file-server/api/swap.go`, comment: "workaround to support
   Opensea's collection page"). So OpenSea has an FF-specific metadata arrangement.
2. **V2 tokenURI never pointed at the API.** All 17 V2 contracts' `tokenURI` =
   `https://ipfs.bitmark.com/ipfs/<cid>/metadata.json` (chain-audited 2026-08-28,
   `ops/bitmark-cdn-retirement/audit_2026-08-28.csv`). The "goes through the FF API"
   behaviour lives on OpenSea's side of the integration, not on chain.
3. **The on-chain metadata docs have NO collection fields.** Checked raw docs for
   three contracts incl. this one (`tools/metadata-regen/src/` cache): no
   `collection_name`, no `collection_uuid`. Byte-preserving regen means the new docs
   don't either. Note: Infinite Entropy's docs are the **2021 legacy format**
   (`bitmark_id`, `prev_provenance`, no `id`/`symbols`/`access_artwork_files`) — one
   of the 326 legacy-format tokens noted in the goal-2 records; possibly related to
   why this contract's integration path differs.
4. **The split is exact.** The verified collection
   `opensea.io/collection/infinite-entropy-by-rafael-rozendaal` (BY FERALFILE badge,
   FF banner) now shows exactly the **8 untouched tokens**. The suffixed duplicate
   `…-447173843` holds the refreshed tokens and shows the collection-level delist
   notice. Item-level (public persisted GraphQL, `itemByIdentifier.__typename`):
   **15/15 refreshed tokens = `DelistedItem`**; of the 9 untouched, 8 = `Item`
   (pages load via direct URL) and 1 (`…7086293946`, Infinite Entropy 5 #1) is also
   item-delisted (was already delisted when first checked; timing unknown).
5. **No other collection is affected BY OUR UPDATE — final scan (6,179 tokens).**
   Fixed tokens: **15/5,930 delisted, all on this contract; 0 of the 5,865 fixed
   tokens on the other 16 contracts** (HLS 50 included, all clean). Controls
   (untouched tokens on the same contracts): **12/249 delisted** — 1 on this
   contract + 11 scattered over 6 others (Primordium ×3, 0x29c9e04e ×3,
   0x7a9ea7 ×2, 0x63c828/0x7a15b3/Rewilded ×1 each). So untouched FF tokens carry
   a ~4–5% BACKGROUND item-delist rate (individual flags, reasons unknown,
   unrelated to our refresh — fixed tokens on those same contracts have zero),
   while Infinite Entropy's 15/15 stands far above background and has the
   duplicate-collection mechanism behind it. The 11 background delists are a
   SEPARATE follow-up (see below). Report:
   `ops/cdn-retirement-phase2/opensea_delist_report.csv`.
6. **The `ipfs://` format itself is fine.** OpenSea translates `ipfs://<cid>?query`
   to its own gateway with query params preserved (observed live:
   `ipfs2.seadn.io/ipfs/<cid>/?edition_number=1&blockchain=ethereum`), and ~2,027 V2
   tokens have carried `ipfs://…?edition_number=…` animations on chain without issue.
   The delisting is a collection-grouping problem, not a media-format problem.

## Hypothesized chain of events (fits all facts, not yet confirmed by OpenSea)

refresh dispatched → OpenSea re-fetched metadata for the 15 tokens **via tokenURI
directly** (integration bypassed for this contract — cause unknown: per-collection
integration config gap? legacy metadata format? OS2 migration behaviour?) → docs
lack collection fields → tokens dropped out of the verified collection → OpenSea
auto-created a new collection from contract/series naming → same display name as the
verified collection → automated fake-collection detection → duplicate delisted.

## What is NOT known yet

- Whether OpenSea actually skipped the FF API for these 15 during the refresh.
  **Checkable on our side**: feralfile.com API access logs around 2026-09-01
  (the refresh window) — did OpenSea request
  `/api/contracts/0x0a5c44da…/tokens/<id>` at all, while other contracts' endpoints
  were hit? That would turn the hypothesis into fact.
- Why only this contract. Candidates: legacy-2021 metadata format (fact 3),
  a missing entry in OpenSea's per-collection integration config, or something in
  the OS2 platform migration.
- Why 1 of the 9 untouched tokens is also item-delisted.
- Whether OpenSea's fix will be config (re-point integration) or manual
  (merge tokens back + remove duplicate) — asked in the email to Ryan.

## Current state / holds

- **Phase-2 chain rollout is PAUSED** (V3 ~2,341 txs + crystalline setTokenBaseURI
  are ready but NOT sent): V3 contracts are the same tokenURI-direct shape, so the
  same re-bucketing risk applies until the metadata-path question is answered.
  Everything up to and including doc regen + pinning is done and verified
  (see `ops/cdn-retirement-phase2.md`).
- Email sent to Ryan @ OpenSea proposing the fix: point this collection's metadata
  back at the FF API like the others, restore the 15 into the verified collection,
  remove the duplicate.

## What resolution needs (for whoever picks this up)

1. Confirm the bypass with FF API access logs (see above) — operator query, prod-01.
2. Drive the OpenSea thread: restore + duplicate removal + an answer to "what
   metadata source does your pipeline use for each of our collections, and can we
   get the list?" — that list is the precondition for unpausing phase 2.
3. Decide the durable posture: the phase-2/3 end goal is FF-independent metadata,
   which ultimately CONFLICTS with API-injected collection grouping. Long-term
   either (a) the on-chain docs gain collection fields (touches the regen rule —
   currently byte-preserving), or (b) collection grouping moves to OpenSea-side
   config (collection metadata editor / contract-level settings) so the docs can be
   FF-free without regrouping risk. This decision gates phase 3's
   `setTokenBaseURI` switches too.
4. Before unpausing: re-run `tools/opensea/delist-scan.py` after any V3 trial
   contract (smallest first) as the canary check.

## Separate finding — background item-level delists (not phase-2 blocking)

11 untouched tokens across 6 contracts are individually delisted on OpenSea with
no connection to our updates (their contracts' FIXED tokens are all clean).
Sampled controls were only ~15/contract, so extrapolated across all FF tokens the
true count could be substantially higher. Worth a full-population sweep with the
same scanner and its own investigation/appeal track. Token list is in the report
CSV (`group=control:untouched, status=DelistedItem`).

## Artifacts

- Scanner: `tools/opensea/delist-scan.py` (public persisted GraphQL, no auth,
  resumable; `DelistedItem` typename = delisted)
- Scan state/report: `ops/cdn-retirement-phase2/opensea_delist_state.jsonl`,
  `…/opensea_delist_report.csv`
- Goal-2 fix records: `ops/bitmark-cdn-retirement/` (result.csv = the 5,880;
  audit_2026-08-28.csv = full-contract audit incl. the 24 IE tokens)
- Phase-2 plan + status: `ops/cdn-retirement-phase2.md`
- Server metadata/collection-injection code: `feral-file-server/api/swap.go`
  (`getEthTokenMetadata`)
