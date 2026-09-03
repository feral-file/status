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
