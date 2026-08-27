# bitmark-reference

Reference phase for the Bitmark-era works: `ipfs_reference` rows mapping each work's CDN preview
path to its byte-verified copy inside the pinned series directory. The server's metadata
generators read this table, so when a work migrates its on-chain metadata comes out as `ipfs://`.

```bash
python3 tools/bitmark-reference/gen-sql.py --verify 20 > bitmark-reference.sql   # after the series are pinned on prod-02
psql … -f bitmark-reference.sql                                                  # review counts, then COMMIT
```

1,927 rows for 4,959 not-yet-migrated works (the 4 swap_initiated share files with still_bitmark editions) (215 path rows + 1,712 query rows, the server's two-row convention
for software previews). Gap-fill only (`ON CONFLICT DO NOTHING`): rows that already exist — the migrated editions of the same series minted from them — are listed and skipped, never rewritten. Does not touch `artworks.preview_uri` (the site keeps playing from the
CDN) or thumbnails (imagedelivery.net, not in the archive).

## Finding, 2026-08-27

Checked against the production DB: every one of the 4,959 not-yet-migrated works already has an
`ipfs_reference` row (1,838 rows → 215 distinct `Qm…` CIDs, one per series preview file, added by
the server at publish time). All 215 answer 200 on `ipfs.feralfile.com` and, sampled, on ipfs.io
(`ops/3435-hls-fix/bitmark_existing_refs*.csv`). So this SQL inserts nothing today; keep it as the
regeneration path if a row ever goes missing. The live risk is whether those 215 CIDs are *pinned*
on prod-02 rather than merely cached — see `tools/bitmark-pin/check-existing-refs.sh`.
