# Retiring the CDN as the only copy — execution plan

*Drafted 2026-08-28 from the 2026-08-25 census and the feral-file-server code. Owner: Brandon (infra), with Hieu for server changes. Tracks feral-file/feral-file#3435 (reference phase) and #3463.*

## Goal

No published work's media is reachable **only** through `cdn.feralfileassets.com` (CloudFront `d1l3yxhqoo0dav.cloudfront.net`). Every reference a wallet, indexer, FF1 or the site follows resolves to a content-addressed copy — `ipfs.feralfile.com` first, any public gateway as fallback — so the CDN becomes an optional cache and can be switched off without a work going dark. Measured by the census: the "depend entirely on us" bucket goes to 0 for Ethereum/Tezos works, and the Bitmark-era bucket shrinks as #3463's migrations land.

## Where the CDN is load-bearing today

Two different populations, two different mechanisms.

| Population | Count (census 2026-08-25) | How the CDN gets into the reference | What consumes it |
|---|---|---|---|
| **A. Ethereum works whose on-chain metadata points at the CDN** | **17,247 works, 24 exhibitions**, all ETH (crystalline work 9,048 · Unsupervised 4,310 · I KNOW 669 · Peer to Peer 611 · Chain Reaction 600 · Social Codes 278 · Field Guide 251 · …) | V3+/V4 `tokenURI` = `https://feralfile.com/api/contracts/<c>/tokens/<id>`. The server builds `animation_url`/`image` from `ipfs_reference`; when no row exists it falls back to `thumbnail.GetPreviewURL` = CloudFront URL. These exhibitions have **no `ipfs_reference` rows** (13,944 artworks without one, per the DB check on 2026-08-28). | Wallets, OpenSea, ff-indexer-v2 (→ FF1, DP-1 feeds), the token-health sweep |
| **B. Bitmark-chain works (no on-chain metadata)** | **4,959 works, 215 series** | `artworks.preview_uri` is a CDN-relative path; the web client prepends `cloudFrontEndpoint`; the FF API's `previewURI` is consumed by the indexer and FF1. Their `ipfs_reference` rows exist (215 `Qm…` CIDs, pinned on prod-02 2026-08-28) but nothing *serves* them because there is no metadata layer to put `ipfs://` into. | feralfile.com, FF1 via the indexer, DP-1 feeds |

Resource shapes on the CDN (population A): `animation_url` html 9,789 · `image` jpg 10,579 · `animation_url` mp4 4,745 · directory previews 6,752 · png 464. Thumbnails on `imagedelivery.net` (Cloudflare Images, 872 rows) are a third dependency and out of scope here.

What is **already done** and this plan builds on: prod-02 holds and pins every CID the DB or the chain references (74,311 recursive pins), mirrors the 215 Bitmark-era series from the custody node, and announces everything with kubo 0.39's sweep provider; the archive manifest CIDs resolve from ipfs.io (228/230).

## Principles

1. **The reference changes, not the bytes.** Every file is pushed to IPFS as-is (same `ipfs add` path the server already uses, `pin=true`), so a CID is a proof of the same content the CDN served.
2. **Serve from our gateway, fall back to any.** New references are `ipfs://<cid>/…` in metadata (the API rewrites to `https://ipfs.feralfile.com/ipfs/…` on the way out, as it does today for V2). The site and FF1 get the gateway URL; a wallet that prefers its own gateway can.
3. **CDN stays up until the census says nothing needs it.** No cut-over by calendar.
4. **Population A first** — it is the one whose *on-chain* promise is currently broken; B is a site/indexer routing question and partly dissolves with #3463.

## Phase 1 — Population A: give every Ethereum work an `ipfs_reference` (server + infra)

The server already contains the mechanism: `internal/tasks/ipfs.go ensureIPFSReferenceForURI` downloads the file (or the software folder) from S3, `ipfs add`s it to prod-02 and upserts the row(s) — the same code that produced the 23,252 rows that exist. It just was never run for these exhibitions.

1. **Enumerate** (read-only SQL, Hieu or Brandon): every `artworks` row in an exhibition with `mint_blockchain in ('ethereum')` whose `preview_uri`/`thumbnail_uri` has no `ipfs_reference` row, grouped by exhibition and series, with sizes from S3 (`aws s3 ls --summarize` per series prefix). Expected ≈ 13,944 artworks over 24 exhibitions; software series share a folder per series, so distinct pushes are far fewer than artworks.
2. **Capacity check** (Brandon): prod-02 has ~250 GB free under `StorageMax` 900 GB. If the enumeration exceeds ~200 GB, resize first (ff-deploy: volume + `storage_max`, same runbook as PR #27).
3. **Run the push** (Hieu): a one-off task/CLI that calls `ensureIPFSReferenceForURI` per distinct `preview_uri` (path-only for software, the query rows follow the server's two-row convention automatically), exhibition by exhibition, smallest first. Log `uri → ipfs_uri`. This is the server's own code path, so what it writes is exactly what a fresh publish would write.
4. **Verify** (Brandon): `tools/pin-referenced` against a fresh DB export → present + pinned; `tools/archive-probe`-style HEAD of a sample through `ipfs.feralfile.com` and ipfs.io.
5. **Flip the metadata** — nothing to deploy: `GET /api/contracts/<c>/tokens/<id>` reads `ipfs_reference` at request time, so wallets and the indexer see `ipfs://` on their next fetch. For OpenSea, trigger the existing refresh task (`internal/tasks/opensea.go`) per exhibition.
6. **Measure**: run the census (`docker compose … run token-health census` on prod-02); population A should move from `dependent` to `independent` exhibition by exhibition. Publish the delta on status.feralfile.com.

Exit: census `dependent` count for Ethereum/Tezos = 0 (was 17,247).

## Phase 2 — Population B: stop routing Bitmark-era previews through the CDN

The reference rows exist; the consumers do not use them.

1. **API**: add a resolved preview URL to the artwork payload — `previewURL` = `https://ipfs.feralfile.com/ipfs/<cid>/<path>` when an `ipfs_reference` row exists for `preview_uri`, else the CloudFront URL as today. One field, additive, no client change required to ship it. (Server: `dto/artwork.go`, the same `PreviewIPFSRef` relation `swap.go` already loads.)
2. **Web client**: `getArtworkPreview` prefers `previewURL` when present (`feralfile-client/src/app/core/logic/artwork.logic.ts`). Behind an environment flag; roll out per exhibition by watching gateway error rates.
3. **Indexer / FF1 / DP-1**: ff-indexer-v2 reads the FF API; confirm it takes `previewURL` (or resolves `ipfs://`) so FF1 playlists point at the gateway rather than the CDN. Coordinate with #3485 (render probe) so "plays" is measured on the new URL.
4. **Migration path stays primary**: #3463 moves these works to Ethereum/Tezos with `ipfs://` metadata; each migrated series leaves population B for good. Phase 2 is the interim so a CDN outage cannot dark them meanwhile.

Exit: no `cdn.feralfileassets.com` URL in any FF API response for a Bitmark-era work; FF1 playlists for those works carry gateway URLs.

## Phase 3 — Gateway as the primary media origin (infra)

Once the site and FF1 fetch from `ipfs.feralfile.com`, prod-02 is in the serving path for all Bitmark-era and (via wallets) Ethereum media.

1. **Edge cache in front of the gateway**: proxy `ipfs.feralfile.com` through Cloudflare (orange-cloud the DNS record; ff-deploy's Caddy stays the origin). Content-addressed paths are immutable, so cache TTLs can be long (`Cache-Control: public, max-age=29030400, immutable` — kubo already sets this for `/ipfs/` paths). This is the CDN's job done by a cache that is *not* the source of truth.
2. **Origin headroom**: prod-02 is a single droplet; measure bandwidth (VictoriaMetrics: Caddy/ipfs container egress) before and after Phase 2 rollout; size up or add a second gateway node from the same pinset if needed.
3. **Announce policy**: keep `Reprovider.Strategy=all` on prod-02 (sweep provider completes); ff-pin-1 to `all` after its kubo upgrade. Public-gateway fallback then works for every block, not only roots.
4. **Monitoring**: token-health daily sweep already probes `ipfs://` through `ipfs.feralfile.com` first; add a gateway 5xx/latency alert in Grafana.

Exit: a synthetic outage of the CDN (block `cdn.feralfileassets.com` in a test client) leaves every sampled work playable.

## Phase 4 — Retire

1. Census + probe show 0 CDN-only works across Ethereum/Tezos and every Bitmark-era series has a gateway route.
2. CloudFront distribution → read-only for 30 days, watching 4xx on the CDN hostname (anything still hitting it is an unknown consumer).
3. Remove `cloudFrontEndpoint` fallback from the client; `thumbnail.GetPreviewURL` returns the gateway form; S3 stays as the cold origin for `ensureIPFSReferenceForURI` and the archive `pin_works.sh`.
4. Update Canon `reference/dependency-register.md` (the CDN row) and status.feralfile.com's method text.

## Order and dependencies

```
Phase 1 (A: push refs)  ──►  census shows dependent → 0 for ETH  ──┐
Phase 2 (B: API + client + indexer)  ──►  FF1/site off CDN  ────────┼──►  Phase 3 (edge cache, capacity)  ──►  Phase 4 (retire)
#3463 migrations (shrinks B)  ────────────────────────────────────┘
```

Phase 1 and 2 are independent and can run in parallel; Phase 3 must land before Phase 2's client flag goes to 100%.

## Open questions to settle before Phase 1 starts

- **Size of population A on S3** — decides whether prod-02 needs another resize first.
- **Software previews with per-edition `?edition_number` queries** (crystalline work et al.): confirm `ensureIPFSReferenceForURI` handles the folder push + two-row convention for V4 works the same way it did for Tezos software (it should — same function).
- **OpenSea refresh throughput** — 17k tokens; the existing task batches, but check rate limits.
- **imagedelivery.net thumbnails** (872 rows) — separate follow-up; the site's grid thumbnails would still be a Cloudflare Images dependency after this plan.

## What already exists to reuse

- `tools/pin-referenced` — verify/pin every referenced CID after each push batch.
- `tools/archive-probe` — public-gateway resolution of archive roots; adapt for a sample of population A.
- `tools/census-rescan` — re-probe a subset without a full census.
- The census itself (prod-02, `run --rm token-health census`) — the acceptance test for every phase.
- ff-deploy PR #27 runbook — the volume resize sequence.
