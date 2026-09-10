# Census 2026-09-09 — the publishing run, and the four hand corrections in its CSV

*Recorded 2026-09-10. Owner: Brandon. Run: agentic-workflows image
`token-health-f6367b711223` on prod-02, `docker compose run … census`,
2026-09-09 10:00 → 2026-09-10 00:37 UTC (14.6 h). Raw summary:
`../census_summary_2026-09-09.md`. Published CSV:
`data/census/token_census_20260909T100006Z.csv`.*

## The run

First census that reads Ethereum metadata from `tokenURI` on chain and fetches
through a gateway Feral File does not operate (Filebase dedicated gateway as
primary; ipfs.io / dweb.link / Pinata as backups — plan:
agentic-workflows `token-health-monitor/docs/plan-tiered-gateway-pool.md`).

| | raw run | published CSV |
|---|---|---|
| tokens | 34,987 | 34,923 |
| rows | 106,174 | 106,116 |
| metadata errors | 67 | 0 |
| verdict redundant / independent | 49,015 / 21,973 | 49,019 / 21,975 |
| ff_only / unreachable / unmeasured | 0 / 0 / 0 | 0 / 0 / 0 |
| public fetch | Filebase 70,987, Pinata 1, fail 0 | + 4 rows dweb.link, 2 rows Pinata (hand-measured, below) |

Primary usage 19,260 requests / 17.2 MB of headers. 288 references the
primary could not fetch in time (502/504/timeout on a cold CID) were deferred
and retried every 10 min: 287 resolved on Filebase, 1 on Pinata after ipfs.io
answered its only request of the run with 429 (`Retry-After: 900`). No
circuit opened.

Phase-3 populations the run makes visible (nothing to do this phase):
14,591 ETH tokens whose `tokenURI` is an `https://ipfs.bitmark.com/ipfs/…`
URL (V2/V3 base URIs), 14,831 already `ipfs://`, 199 `data:` URIs; 199 media
rows whose on-chain URL is an FF gateway URL (Peer to Peer 135 on
ipfs.bitmark.com, exhibition 4225a453 64 on ipfs.feralfile.com).

## The 67 tokens the raw run could not read, and what was done

The raw CSV had 67 tokens with a single `metadata` row carrying
`tokenURI read failed …` and no media rows. `build.py` classifies a work from
its media rows only, so these 67 were absent from the page (34,920 works
instead of 34,987). Investigated one by one:

### 64 × CRAWL tokens burned in on-chain merges — DROPPED from the CSV

Exhibition CRAWL (`3c4b0a8b…`, contract `0x81c882c59799eA442317D020c39174AaAa8d7FC7`,
FeralfileExhibitionV4_3) has `burn: true`: CRAWL MULTI LEVEL tokens are minted
by burning others. The API still lists the burned inputs as artworks
(`blockchainStatus: settled`, `ownerAddress` = the zero address); the API lists
543, the chain holds 479 (`totalSupply`). `tokenURI()` reverts for all 64, and
the 64 are exactly the API's zero-owner set. Not works: their 64 rows were
removed; ids in `crawl_burned_64_token_ids.txt`. Previous censuses counted
them because the API metadata endpoint still serves a document for a burned
token.

Checker follow-up (agentic-workflows): exclude API artworks whose
`ownerAddress` is the zero address from the universe and report the count;
keep a `tokenURI` revert as a metadata error for anything else. API follow-up:
a burned flag on artworks, so census, indexer and status stop guessing.

### 1 × CRAWL MULTI LEVEL[043,105] (`…030383764`) — metadata unresolvable on chain; FIXED BY HAND in the CSV, owner tx pending

Live token (owner `0xFdFfCa12…`), merged on chain 2025-08-16 from indexes 43
and 105. Timeline:

1. 2024-07-19 contract deployed (owner `0x1d05cf6c…`); 533 minted in July,
   merges through September.
2. 2024-09-04 06:00 the last two merges of that year (`…762`, `…763`) minted;
   06:03 the server regenerated the whole metadata directory →
   `QmXfp5m5RLjooUJE5CsTSMK6R3qdXqK8G8NmCF8VFaf4vb` (542 docs).
3. 2025-08-16 `…764` minted on chain; the DB got no artwork row for it.
4. 2026-02-02 10:15 the only `setTokenBaseURI` in the contract's history
   (tx `0x50cb1741969351bf8a7345dfbc66e347f4053ef37fdf280dc22213b468c09d15`,
   block 24368511, from the owner) → `ipfs://QmXfp5…`.
5. 2026-07-02 04:47:03 the DB created the `…764` artwork and, the same second,
   regenerated all 543 docs → `QmfK7MjgYTwyAuRWCS44WzGNFzCd3y2Msu1BeJp1VqwJ47`
   and repointed every artwork's `ipfs_cid` to it. The chain base URI was not
   updated: `tokenURI(…764)` → `ipfs://QmXfp5…/…764` → 404 (the directory
   predates the token). DB has led the chain for the whole contract since.

Old vs new directory, all 542 shared docs compared: `image` / `animation_url`
identical; differences confined to `royalties.shares` (platform 2.5% address
`0x2033606bE146405870F92Ea3144ef5057b9DEA48` → `0x080FEB125bA730D6D12789B6AAAB01f4E31D8Bd1`),
`description` / `exhibition_info` (`<br><br>` → `\n\n`, 12,778 places),
`access_artwork_files` (`’` → `'`), `timestamp`.

Fix: one owner tx, `setTokenBaseURI("ipfs://QmfK7MjgYTwyAuRWCS44WzGNFzCd3y2Msu1BeJp1VqwJ47")`
(same form as the stored value: no trailing slash), requested from Hieu
2026-09-10; no OpenSea refresh afterwards. The CSV records the post-fix state:
metadata row `ipfs://QmfK7M…/…764` (the doc is served by ipfs.feralfile.com),
media rows for its two files hand-measured 2026-09-10 from Brandon's machine —
ipfs.feralfile.com 200, gateway.pinata.cloud 200, cid.contact routing 404
(no provider record) → `independent`.

### 1 × For Your Eyes Only #96 (`0x6DBa1302…`, FYEO, Bitmark-era) — checker bug + DB drift; FIXED BY HAND in the CSV, SQL prepared

The completed swap (2024-05-22, `swapArtworkFromBitmark`, tx
`0xdb369ecc79becf3c9e09319d7a9b5440d7dec1199dca080f300846b40ab54578`) left
`swaps.token` and the artwork's token id as the Bitmark 64-hex id instead of
the decimal uint256 every sibling has; the checker's id parser only reads hex
with a `0x` prefix and failed. On chain the token id is that hex as uint256
(`58715691114557290052923369262590057385049903455696195926578851682062958379139`;
`ownerOf` = the swap's recipient; `tokenURI` =
`https://ipfs.bitmark.com/ipfs/QmRB42NjEJdqoHXGDSWmY4xk5ZhVq8sssKPChYc3WNFWYo/metadata.json`
= `swaps.ipfs_cid`). DB alignment: `fyeo-96-swap-token-align.sql`, applied
2026-09-10 (`UPDATE 1` twice). Checker follow-up (recorded, not filed): accept a
64-hex token id. CSV: metadata row set to that tokenURI (200); media rows
hand-measured 2026-09-10 — ipfs.feralfile.com 200, dweb.link 200 (Pinata
200), cid.contact 4 non-FF providers → `redundant`. The row keeps the hex
token id the census recorded; the next census will carry the decimal one.

### 1 × The Bardo #174 (`0xaa02CC02…`, Bitmark-era) — transient RPC error; FIXED BY HAND in the CSV

The RPC closed the connection once while reading `tokenURI`; the checker does
not retry transport errors on the RPC (follow-up: one retry). Confirmed by
hand: `ownerOf` = `0x85413BDF…`, `tokenURI` =
`https://ipfs.bitmark.com/ipfs/QmYAnKXz3Kd5NxQ1X19SEAdkEgArrqF6XMBFbieDz5pfkL/metadata.json`.
CSV rows as for #96 (dweb.link 200, cid.contact 4 non-FF providers →
`redundant`).

## What the hand-measured rows are NOT

Six media rows (two tokens × 2 for FYEO/Bardo, two for CRAWL `…764`) were
measured from a laptop, not by the census on prod-02: public fetch through
dweb.link or gateway.pinata.cloud instead of Filebase, routing through
cid.contact instead of delegated-ipfs.dev. Same signals, same verdict rule
(`census.verdict`), different vantage point. They are identifiable in the CSV
by `public_fetch` = `ok:dweb.link` / `ok:gateway.pinata.cloud` with `detail` =
`routing=cid.contact`.
