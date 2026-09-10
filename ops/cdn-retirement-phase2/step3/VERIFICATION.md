# Step-3 regen verification record (2026-09-03, verify-regen.py + light pass)

Independent of the regen tools' mapping logic.

## V3 (2,341 docs, six contracts) — full strength
- Doc integrity: **2,341/2,341** — reverse-substitution byte proof (substituting
  the new media values back yields the original on-chain doc byte-for-byte)
  + JSON key/value deep-equality outside media keys.
- Media 1:1 content: **1,782/1,782 deduped pairs** — old CDN URL (params
  intact, relative paths CDN-hosted) vs new ipfs target via ipfs.feralfile.com;
  full byte equality ≤4 MB, head-64KB + Content-Length above. Zero failures.
- Report: verify_v3.csv (empty = no failures).

## crystalline (9,048 docs) — per operator's spec (correspondence + samples)
- Doc integrity: **9,048/9,048** (same reverse-substitution byte proof).
- Offline correspondence, all tokens: animation **9,048/9,048** (query params
  incl. hourIdx byte-identical, same nft.html basename); image **9,048/9,048**
  (same filename, ?variant folded to the correct generated_images/<v>/ path).
- Content: nft.html CDN vs ipfs byte-identical (1,855 B, checked once —
  shared by all 9,048); random 30-image sample **30/30 byte-identical**
  (CDN ?variant URL vs folded ipfs path).

Conclusion: every regenerated doc differs from its on-chain original ONLY in
media values, and the media replacements are 1:1 (V3: fully content-proven;
crystalline: structurally proven for all + content-sampled).

## ipfs://<cid>?query resolution — live third-party evidence (2026-09-04, Chrome + OpenSea)

Question: do platforms OUTSIDE the FF API preserve query params (edition_number,
hourIdx) when resolving `ipfs://` media? Measured on live tokens:

- **Infinite Entropy 5 #1** (V2 `0x0a5c44da…`, chain doc animation
  `ipfs://QmPoWQ…?edition_number=1&blockchain=…`, no API mediation):
  OpenSea's iframe = `https://ipfs2.seadn.io/ipfs/QmPoWQ…/?edition_number=1&blockchain=ethereum`
  — **their own gateway, query params preserved**. (The token happens to be
  DELISTED by OpenSea — "suspected ToS violation", side-finding worth its own
  follow-up — so media is suppressed, but the URL translation is the proof.)
- **peep-o-rama #1** (The Bardo, V2 `0xaa02cc02…`): iframe =
  `https://ipfs.feralfile.com/ipfs/QmbTnb…?edition_number=…` (OpenSea cached
  the API-rewritten form) — piece loads with a working progress bar.
- **filum #1** (Truth): OpenSea's iframe = the CDN overlay URL — OpenSea's
  stored metadata for this contract is the FF-API output, NOT the chain doc;
  filum is not a valid test of ipfs:// handling (confirms the operator's
  point about the FF↔OpenSea metadata path).

Conclusions: (1) `ipfs://<cid>/<path>` and `ipfs://<cid>?query` are both
handled by OpenSea with params preserved; 2,027 V2 tokens have shipped the
query form on chain already. (2) OpenSea's per-token media source varies by
indexing history (API form vs native ipfs translation) — post-rollout
`refreshOpenSeaTokensMetadata` is what makes it re-read the new docs.
(3) The residual risk is third-party gateway COLD-FETCH latency (seadn's
first fetch can time out; ipfs.io served the same CID in 10 s, dweb 1.8 s,
5 DHT providers) — availability warm-up, not format. Trial-series visual
check on OpenSea after the first contract remains the gate.
