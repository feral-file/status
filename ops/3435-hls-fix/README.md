# 3435 — prod-02 pin gap, HLS fix, archive mirror (2026-08)

Working record for feral-file/feral-file#3435, step 1 (prod-02 gateway) and
the "184 gateway-gap works" remediation. Tools live in `tools/`; this
directory holds the inputs, the exact bytes that were pinned, and the results.

| File | What |
|---|---|
| `prod02-ipfs-diagnosis.md` | Diagnosis: 4,448 failed probes = 47 CIDs; 44 never pinned (`Gateway.NoFetch`), 3 HLS master playlists. Runbook used. |
| `prod02_missing_44_cids.txt` | The 44 Tezos thumbnail/display CIDs pinned on prod-02 on 2026-08-25 (all 200 on `ipfs.feralfile.com` after). |
| `rewilded_eth_tokens.csv` | Rewilded Topography #1 — the 54 ETH editions, classed HLS / MP4-IPFS / CDN, with each token's `tokenURI` metadata CID. |
| `rewilded-metadata-fix/` | ETH: `gen.py` → `dirs/<edition>/metadata.json` (50, only `animation_url`/`image` changed) → `pin.sh` → `result.csv` (edition, token, old CID, new CID). Input to `tools/update-token-uri`. |
| `db/` | The DB changes as applied: `hls-fix*.sql` (8/25, HLS references), `fix-empty-cid-refs.sql` (8/28, 157 rows rebuilt), `delete-truncated-orphan-refs.sql` (8/28, 9 orphans). |
| `archive_probe_prod02_baseline_2026-08-26.csv` | Before the mirror: prod-02 served 5 of 230 manifest CIDs. |
| `bitmark_pin_verify_2026-08-27.log` | After the mirror: 215/215 series pinned recursively and 200 on `ipfs.feralfile.com`. |
| `bitmark_existing_refs_probe_2026-08-27.csv` | The 215 `Qm…` CIDs the DB's `ipfs_reference` rows point at for the 4,959 not-yet-migrated works: 215/215 on our gateway. |
| `pin_referenced_2026-08-28.csv`, `pin_chain_only_2026-08-28.csv` | Every DB-referenced CID (73,385) and every chain-referenced CID the DB lacks (198): all present, all pinned. |
| `census_summary_2026-08-25.md` | Second census, run on prod-02. |
| `feralverse-metadata-fix/` | Tezos: `tokens.csv` (142 token_id → current metadata URI) → `gen.py` → `files/<token>.json` (only `artifactUri`/`formats[0]`) → `pin.sh` → `result.csv`. Input to `tools/update-tezos-metadata`. |

Replacement media (all pinned on prod-02, resolving on ipfs.io):

| Series | Old (HLS master) | New (MP4) |
|---|---|---|
| Rewilded Topography #1 `7b77f5d5` (ETH) | `QmQJAa9uC5…` | `QmV6a8NCQDTq1pMddqgMNg9xutBkp7oa2EJTspi5tH7z6C` (pre-existing, byte-identical to CDN) |
| FeralVerse `506e46e1` (Tezos) | `QmRGwoEnB4…` | `bafybeiagkwrb4av4e27x2fihhwl3q3oa5uqp42wynjd5vksfiswouz4tka` |
| FeralVerse `45c0f2cc` (Tezos) | `Qmf8bvobDW…` | `bafybeifu35t24hzfbq7voe5n3xe4sbclckrs6vsn2b5xixtv3togk4yi2u` |

## Status (2026-08-25)

- [x] 44 missing thumbnail/display CIDs pinned on prod-02 (`ipfs.feralfile.com` 44/44 → 200)
- [x] 3 MP4s pinned (prod-02 + DHT); Rewilded reuses the pre-existing `QmV6a8…`
- [x] 50 ETH metadata dirs pinned; `updateArtworkEditionIPFSCid` executed for all 50 (`tools/update-token-uri check` → 50/50)
- [x] 142 Tezos JSONs pinned; `update_edition_metadata` executed by trustee `tz1fcVFFVujFmnDsWEV1nhGukJTkgXtDKZmm`, 1 trial + 8 batches, 11:44–11:55 UTC (`tools/update-tezos-metadata check` → 142/142)
- [x] DB: `tools/db-sql/hls-fix.sql` applied (ipfs_reference ×3, preview_mime_type, swaps.ipfs_cid ×50, artworks.metadata.ipfs_cid ×142)
- [x] census 2026-08-25 on prod-02; page rebuilt (gateway-gap 184 → 0)
- [x] prod-02 volume 1000 GB / StorageMax 900 GB (ff-deploy#27); 215 Bitmark-era series mirrored from ff-pin-1 (verify 215/215)
- [x] every DB- and chain-referenced CID pinned on prod-02 (73,385 + 198; 74,311 recursive pins) — they had been unpinned cache
- [x] ff-pin-1: `Reprovider.Strategy=roots`, ConnMgr 100/250, restart; roots announced by `/root/provide-roots.sh` (cron 03:00 UTC); archive probe ipfs.io 218 → 228/230
- [x] `ipfs_reference` cleanup: 157 rows rebuilt, 9 truncated orphans deleted
- [ ] optional: `setTokenBaseURI` → `https://ipfs.feralfile.com/ipfs/` (`tools/update-token-uri base-uri-tx`)
- [ ] unpin superseded HLS metadata (50 ETH dirs, 142 Tezos JSONs, 3 playlists) once nothing references it
- [ ] ff-pin-1 kubo 0.32 → 0.39 (sweep provider), then `Reprovider.Strategy=all` and retire the provide loop
- [ ] next phase: retire the Bitmark-era CDN links — see `ops/bitmark-cdn-retirement.md`

Order of operations: `gen.py` → `pin.sh` (IPFS tunnel) → chain update tool
(`tools/update-token-uri`, `tools/update-tezos-metadata`) → DB
(`tools/db-sql/hls-fix.sql`) → re-run census → rebuild the page.

`src/` (the fetched originals) is gitignored — `gen.py` re-fetches it, and the
regenerated `dirs/` / `files/` are byte-identical to what is committed (verified
2026-08-25).
