# 3435 — prod-02 pin gap + HLS fix (2026-08)

Working record for feral-file/feral-file#3435, step 1 (prod-02 gateway) and
the "184 gateway-gap works" remediation. Tools live in `tools/`; this
directory holds the inputs, the exact bytes that were pinned, and the results.

| File | What |
|---|---|
| `prod02-ipfs-diagnosis.md` | Diagnosis: 4,448 failed probes = 47 CIDs; 44 never pinned (`Gateway.NoFetch`), 3 HLS master playlists. Runbook used. |
| `prod02_missing_44_cids.txt` | The 44 Tezos thumbnail/display CIDs pinned on prod-02 on 2026-08-25 (all 200 on `ipfs.feralfile.com` after). |
| `rewilded_eth_tokens.csv` | Rewilded Topography #1 — the 54 ETH editions, classed HLS / MP4-IPFS / CDN, with each token's `tokenURI` metadata CID. |
| `rewilded-metadata-fix/` | ETH: `gen.py` → `dirs/<edition>/metadata.json` (50, only `animation_url`/`image` changed) → `pin.sh` → `result.csv` (edition, token, old CID, new CID). Input to `tools/update-token-uri`. |
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
- [ ] optional: `setTokenBaseURI` → `https://ipfs.feralfile.com/ipfs/` (`tools/update-token-uri base-uri-tx`)
- [ ] re-run token-health census; rebuild status.feralfile.com; unpin old metadata once nothing references it

Order of operations: `gen.py` → `pin.sh` (IPFS tunnel) → chain update tool
(`tools/update-token-uri`, `tools/update-tezos-metadata`) → DB
(`tools/db-sql/hls-fix.sql`) → re-run census → rebuild the page.

`src/` (the fetched originals) is gitignored — `gen.py` re-fetches it, and the
regenerated `dirs/` / `files/` are byte-identical to what is committed (verified
2026-08-25).
