# OpenSea metadata path per series — scan results (2026-09-03)

Follow-up to `ops/opensea-metadata-path-incident.md` (feral-file#3435). Goal: list
every Feral File collection whose OpenSea metadata does NOT come through the FF API,
so OpenSea can re-point them, and confirm the FF API is ready to serve them.

## How `collection_name` / `collection_uuid` are generated

`feral-file-server/api/swap.go getEthTokenMetadata`
(`GET https://feralfile.com/api/contracts/<contract>/tokens/<tokenID>`), for contracts
registered as FF exhibition contracts:

| field | if `series.metadata.collectionName/UUID` is set and non-empty | otherwise |
|---|---|---|
| `collection_name` | that value | `"<series.title> by <artist alias>"` (alias = `alumniAccount.alias` with `<A2P>`, `_tez`, `_custody` stripped) |
| `collection_uuid` | that value | `series.id` |

Edge: if `collectionName` is present but **empty string**, the field is omitted
entirely (3 series hit this; fixed in the DB, see below). For contracts NOT registered as an exhibition
contract the API instead computes `collection_uuid = uuid5(ad1eb04a-…, collection_name)`
from a `collection_name` already in the IPFS doc.

The derivation was confirmed against the live API for every scanned Ethereum series
(`ff_api_matches_derivation` column): 0 mismatches.

## Method

`tools/opensea/collection-metadata-scan.py` — for each of the 560 series: derive the
two fields, pick a settled Ethereum token, fetch its OpenSea item page
(`opensea.io/item/ethereum/<contract>/<tokenID>`, no auth). The server-rendered page
embeds the item record OpenSea actually uses, including **`tokenUri`** (the metadata
URL OpenSea reads) and OpenSea's own **`metadataStorageLabel`** (`CENTRALIZED` /
`DECENTRALIZED`), plus the current collection slug / verified flag. Delisted tokens
embed nothing, so up to 3 tokens are tried.

Verdict = `Centralized` when `tokenUri` starts with
`https://feralfile.com/api/contracts/`, else `Decentralized`. OpenSea's label agreed
with this in 100% of cases (0 disagreements).

## Results

| verdict | series | meaning |
|---|---|---|
| Centralized | 290 | OpenSea reads `feralfile.com/api/contracts/…` — safe |
| **Decentralized** | **121** | OpenSea reads tokenURI directly (`ipfs.bitmark.com`, `ipfs.io`) — re-bucketing risk on any refresh |
| Delisted | 22 | every sampled token is `DelistedItem`, no data (Infinite Entropy ×16, 36 Points ×3, Venuses ×1, 2 internal test series) |
| NoEthToken | 127 | Tezos or unminted, out of scope |

Decentralized by contract version: V3 66, V4 28, V4_3 11, V2 14, V4_2 1, AirdropV1 1.
Largest groups: Peer to Peer 12, Gray Matter 12, CRAWL 11, In/Visible 10,
Material Wonderland 9, Infinite Entropy 8 (+16 delisted), I KNOW 8, SOUND MACHINES 8,
One to Zero 8, +GRAPH 6.

Important nuance: **112 of the 121 Decentralized series are still sitting in their
correct verified FeralFile collection** (OpenSea collection name == expected
`collection_name`). The grouping survives from earlier indexing; it breaks only when a
refresh re-reads the doc without collection fields — exactly what happened to Infinite
Entropy. Spot-checked on-chain docs: V3 (Peer to Peer) docs carry **no**
`collection_name`; some V2 docs (For Your Eyes Only) carry `collection_name` but no
`collection_uuid`. So the 121 are all exposed to the same failure on the next refresh,
which is why the phase-2 V3 rollout must stay paused until they are re-pointed.

Oddities (not for OpenSea, for us): `Bridges by HP` sits in an unverified `FFV3 - Test 1`
collection (owner FFDev); the two Da Nang Review series sit in `TestExhibition001`;
`Inaugural SuperBridge Summit` collection is unverified.

## FF API readiness spot-check (`tools/opensea/ff-api-spotcheck.py`, 10 tokens/series)

| | |
|---|---|
| tokens fetched | 878 across the 143 non-Centralized series |
| HTTP 200 | 878 / 878 |
| latency | median 0.46 s, p90 0.59 s, max 0.69 s |
| series with all sampled tokens complete | 143 / 143 (after the DB fix below) |

First pass found 3 failing series, Refik Anadol's *Unsupervised — Burned* (MoMA Dreams,
Data Universe 2D, Data Universe 3D): `series.metadata.collectionName` was `""` in the
FF DB, so the API returned no `collection_name` (uuid was present). Fixed 2026-09-03 by
`fix_unsupervised_collection_name.sql` (collectionName set to the names OpenSea already
displays). Re-check after the fix: 30/30 tokens return the expected `collection_name` +
`collection_uuid`; the derivation check across all series is back to 0 mismatches.

## Files

- `collections_report.csv` — every series, all columns (verdict, derived + live API
  collection fields, OpenSea tokenUri / label / collection slug / verified, sample token)
- `decentralized_collections.md` — handoff table for OpenSea: the 143 non-Centralized
  series with expected `collection_name` / `collection_uuid`, contract, sample token,
  current tokenUri and current collection
- `opensea_handoff.csv` — **the file to send OpenSea**: 138 series (118 reading tokenURI
  directly + 20 delisted), one row each, 9 columns: status, exhibition, collection_name,
  collection_uuid, contract, current OpenSea collection slug, sample token, current
  metadata URL, expected metadata URL. Test/internal exhibitions excluded
  (Smooth = FFV3 test, Da Nang Review = TestExhibition001, Feral File Internal auctions).
- `ff_api_spotcheck.csv` — per-token FF API results (878 rows, 0 problems)
- `fix_unsupervised_collection_name.sql` — the applied DB fix for the 3 empty-name series
- `scan_state.jsonl`, `scan.log`, `spotcheck.log` — raw state / logs (resumable)

Re-run: `python3 tools/opensea/collection-metadata-scan.py --state … --out … --md … --refresh`
(≈25 min at 1 OpenSea page/s); use `--series <id>` for a single collection as a canary
after OpenSea re-points it.

---

# 2026-09-04 — grouping fields frozen; OpenSea's audit reconciled; special-project class opened

## What we did

- **Froze both grouping fields on every ETH series** (`freeze_collection_fields.sql`, as
  applied): `collectionUUID := series.id` where unset (280 rows) and
  `collectionName := "<title> by <PrettyAlias(artist)>"` where unset (283 rows). Values
  are exactly what the API already returned (verified live before applying: uuid 439/442
  equal + 3 n/a, name 283/283 equal), so OpenSea saw zero change; what changed is that a
  series-row rebuild or an alias/title edit can no longer move a token to a new
  collection. Pre-freeze snapshot: `collection_uuid_audit.csv` (280 FALLBACK / 162 FROZEN).
- **Sent OpenSea the authoritative mapping**: `opensea_collection_mapping_2026-09-04-2.csv`
  — 440 series → 294 collections (the `-2` version drops two internal English-auction test
  series, see `followup_to_ryan_csv_correction.md`). Cover letter:
  `reply_to_ryan_2026-09-04.md`.
- **Still open server-side**: new series fall back to derivation until someone sets the
  fields — a publish-time guard in `api/swap.go` (write `collectionUUID`/`collectionName`
  on series creation, or CI check) is needed so the freeze doesn't erode. Not filed yet.

## What OpenSea did / answered (`ryan_reply_2026-09-04.md`, attachment
`opensea_ff_collections_full_2026-09-04.csv`)

| | |
|---|---|
| Infinite Entropy | **fixed**: bound to `71513905-…`, 24/24 tokens back in the verified collection, duplicate empty |
| Bound to our CSV values | 5 collections: Infinite Entropy, Study for Unsupervised, MONOPOLY SET, Peer to Peer Launch Party Exclusive, Inaugural SuperBridge Summit |
| Regrouped | 198 tokens moved from exhibition-level groupings into their series (36 Points, Venuses included) |
| uuid version | irrelevant to them (opaque string); what matters: one stable value per collection |
| The 17 v5 rows | on hold, refreshes paused on them, per our ask |

Their full picture, 410 collections (their `category` column):

| category | n | what it is |
|---|---|---|
| 1 live series in our mapping | 291 | done |
| 2 v5 special-project awaiting freeze | 17 | non-platform contracts, unbound |
| 3 bound to uuid not in our mapping | 39 | 23 IE duplicates (emptied) + 15 special-project bound to v5 |
| 4 exhibition-level grouping | 33 | theirs, one per exhibition, expected |
| 5 auto-created duplicate | 5 | emptied |
| 7 unbound / unidentified | 25 | almost all special-project class |

## The special-project class (NEW — next OpenSea deliverable, promised for the week of 2026-09-07)

Contracts we deployed manually from our address but never published through the server
(Aorist-era projects, a2p, chromatophores, launch-party/summit drops…). No series rows in
our DB, so the API serves their metadata straight from the on-chain docs and derives
`collection_uuid = uuid5(namespace, collection_name)` **per token** (live since
2025-07-21). OpenSea holds **57** such collections; five projects have already forked from
name inconsistencies (a2p-v1 ×2, a2p-v2 ×2, aorist-art ×3, artificial-natural-history ×2,
temporally-uncaptured ×2) plus the coral-arena capitalization split.

What "done" needs:
1. A pinned uuid **per collection** (not per token), stored server-side (no series rows
   to hang it on — design needed in `feral-file-server`), covering all 57, with a chosen
   winner for each fork. v5-derived values can stay as the stored value (Ryan: no cost
   either way; keeping them avoids rebinding the 15 already bound).
2. Send OpenSea the 57-row mapping; they rebind the 17 + fork losers and resume refreshes.
3. Separately (`ops/cdn-retirement-phase2/STATUS.md` item 4): these tokens are outside
   every phase-2 tool (no series → no census pin units, no `ipfs_reference`), so their
   media CDN dependency is unmeasured. Enumerate from the chain before deciding.

## Files (this section)

- `freeze_collection_fields.sql` — the two UPDATEs as applied 2026-09-04
- `collection_uuid_audit.csv` — pre-freeze snapshot of every ETH series' effective uuid/state
- `opensea_collection_mapping_2026-09-04-2.csv` — **authoritative mapping sent to OpenSea** (440 → 294)
- `reply_to_ryan_2026-09-04.md`, `followup_to_ryan_csv_correction.md` — what we sent
- `ryan_reply_2026-09-04.md` — what OpenSea answered
- `opensea_ff_collections_full_2026-09-04.csv` — OpenSea's 410-row attachment (their view; the 57-collection class is categories 2/3/7)
