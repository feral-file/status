# bitmark-reference

Reference phase for the Bitmark-era works: `ipfs_reference` rows mapping each work's CDN preview
path to its byte-verified copy inside the pinned series directory. The server's metadata
generators read this table, so when a work migrates its on-chain metadata comes out as `ipfs://`.

```bash
python3 tools/bitmark-reference/gen-sql.py --verify 20 > bitmark-reference.sql   # after the series are pinned on prod-02
psql … -f bitmark-reference.sql                                                  # review counts, then COMMIT
```

1,931 rows for 4,959 not-yet-migrated works (215 path rows + 1,712 query rows, the server's two-row convention
for software previews). Gap-fill only (`ON CONFLICT DO NOTHING`): rows that already exist — the migrated editions of the same series minted from them — are listed and skipped, never rewritten. Does not touch `artworks.preview_uri` (the site keeps playing from the
CDN) or thumbnails (imagedelivery.net, not in the archive).
