# prod-02 IPFS diagnosis — 2026-08-25 (feral-file#3435)

## Findings (from census 2026-08-03 + live re-probe 2026-08-25)

**A. "4,448 failed CID probes on ipfs.feralfile.com" = 47 distinct CIDs, 3,743 works, 4 Tezos exhibitions + 2 others.**
- 44 CIDs are Tezos `thumbnailUri` / `displayUri` images (JPEG/PNG, 6–500 KB each) for
  Ecotone (12 CIDs, 151 rows each), Simulation Sketchbook (12), Doppelganger (7), Harbingers (13).
- Live today: ipfs.feralfile.com → `404 "block was not found locally (offline)"` on 41,
  `500 "cannot detect content-type: failed to fetch all nodes"` on 3 (partial DAG). ipfs.io → 200 on all 44.
- Cause: `ipfs.gateway_no_fetch: true` (ansible/app_defaults/ipfs/config.yml) is deliberate — the gateway
  only serves locally pinned blocks — and these CIDs were never pinned on prod-02. **Not data loss.**
  The three 500s are partial DAGs (a root fetched once, children evicted by `gc_period: 1h`).
- Fix: `ipfs pin add` the 44 CIDs on prod-02 (pin add fetches from the network regardless of Gateway.NoFetch).
  Total size ≈ 3 MB. List: prod02_missing_44_cids.txt.

**B. The "184 gateway-gap works" = 3 CIDs, all HLS master playlists. Genuinely broken everywhere.**
- FeralVerse (Tezos KT1JCd3Q…, 142 works, artifactUri): QmRGwoEnB4…, Qmf8bvobDW…
- On Screen Presence (ETH 0xaDB3877…, 42 works, animation_url): QmQJAa9uC5…
- The playlists resolve (200 on ipfs.io, ipfs.feralfile.com, dweb.link) but reference *relative*
  variant playlists (`stream_<hash>_r<id>.m3u8`) that cannot be addressed from a bare file CID
  (`<cid>/stream_….m3u8` → 404). The census flagged content-type; the real defect is an unplayable reference.
- Fix ("HLS repackaging"): package the whole HLS tree (master + variant playlists + segments) as one
  directory CID, or an MP4 rendition, pin on prod-02 + ff-pin-1, then update the works' reference
  (Tezos token metadata / FF DB) → new CID. Source masters: cdn.feralfileassets.com previews for those series.

**C. Step 2 (all Bitmark-era media on prod-02) sizing.**
- pin_manifest_2026-08-04.csv: 215 series, 397.6 GB, 16,722 files, on ff-pin-1.
- prod-02 `storage_max: 380GB` (config) — smaller than the Bitmark set alone. Need current repo usage
  + DO volume size before pinning; expect a volume resize + `storage_max` bump (ff-deploy change → PR).

## Operator commands (read-only; run from ff-deploy)

```bash
make ipfs-port-forward ENV=prod HOST=prod-02 IPFS_API_LOCAL_PORT=15001 IPFS_GATEWAY_LOCAL_PORT=18080
# in another shell:
A=http://127.0.0.1:15001/api/v0
curl -s -X POST "$A/repo/stat?human=true"
curl -s -X POST "$A/config?arg=Datastore.StorageMax"; curl -s -X POST "$A/config?arg=Datastore.GCPeriod"; curl -s -X POST "$A/config?arg=Gateway.NoFetch"
curl -s -X POST "$A/pin/ls?type=recursive" | wc -l
curl -s -X POST "$A/swarm/peers" | python3 -c "import json,sys;print(len(json.load(sys.stdin)['Peers']),'peers')"
# confirm the 44 are absent locally (offline check, no fetch):
while read c; do printf "%s " $c; curl -s -X POST "$A/block/stat?arg=$c&offline=true" | head -c 80; echo; done < prod02_missing_44_cids.txt
```

## Remediation commands (mutating — run only after the reads above)

```bash
# Fix A: pin the 44 missing thumbnails/display images (~3 MB)
while read c; do curl -s -X POST "$A/pin/add?arg=$c&progress=false"; echo; done < prod02_missing_44_cids.txt
# verify through the public gateway:
while read c; do curl -s -o /dev/null -w "$c %{http_code}\n" https://ipfs.feralfile.com/ipfs/$c; done < prod02_missing_44_cids.txt
```
