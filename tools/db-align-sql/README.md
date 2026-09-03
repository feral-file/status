# db-align-sql — WHERE-pinned SQL generators for the Feral File back-office DB

Every generator here follows the same discipline (phase-1 rule, kept ever since):

- **The DB follows the chain, never leads it** — align SQL is generated from a
  fresh DB export and run only after the corresponding on-chain state is live
  (the one deliberate exception is recorded in the ops doc that ordered it).
- **Every UPDATE is WHERE-pinned to the exact old value** (plus a second anchor
  such as `series_id` where available), so a drifted row yields `UPDATE 0`,
  never a wrong write. Inserts are `ON CONFLICT DO NOTHING`; existing rows are
  never clobbered — mismatches go to review CSVs.
- Output ends without `COMMIT`: run once with `psql -f` as a free dry-run
  (session end rolls back), check the counts, then re-run with `COMMIT`
  appended.

| tool | aligns | keyed by |
|---|---|---|
| `gen-v3-sql.py` | V3 `artworks.metadata.ipfs_cid` (bare doc CID) after per-token `updateArtworkEditionIPFSCid` rollouts; per-token old→new mapping from `updates_<contract>.csv` | `id` + `series_id` + old CID |
| `gen-v4-sql.py` | V4/V4_2 `artworks.metadata.ipfs_cid` (path form `<dirCID>/<tokenId>`) after a `setTokenBaseURI` dir switch | `id` + `series_id` + old path |
| `truth-db-align.py` | Truth-contract variant with safety diff: refuses on any beyond-media doc difference or unresolvable media CID | see docstring |
| `gen-reference-sql.py` | `ipfs_reference` upserts mapping CDN preview/thumbnail paths onto pinned dir units (query params preserved byte-for-byte); conflicts/unmapped → review CSVs | `uri` |
| `gen-token-sql.py` | per-token metadata-CID UPDATEs from a pin-run `result.csv` (first used for the 3435 HLS fix: rewilded 50 ETH + feralverse 142 Tezos) | token id + old CID |
| `gen-bitmark-reference-sql.py` | `ipfs_reference` gap-fill for Bitmark-era works (CDN preview path → byte-verified copy in the pinned series dir); the server's metadata generators then emit `ipfs://` on migration | `uri`, gap-fill only |

## Notes carried over from the retired per-phase dirs

**Bitmark reference finding (2026-08-27):** every one of the 4,959
not-yet-migrated Bitmark works already had an `ipfs_reference` row (1,838 rows
→ 215 distinct series-preview CIDs, added by the server at publish time), all
answering 200 on ipfs.feralfile.com — so `gen-bitmark-reference-sql.py`
inserted nothing that day. Keep it as the regeneration path if rows ever go
missing; the live risk was pin-vs-cache, handled by `tools/pin-referenced`.

**Truth (phase-2, 2026-09-02):** Truth's 128 census-CDN rows were the filum
`alternativePreviewURI` overlay, out of phase scope — `truth-db-align.py`
needs the DB export (`artwork_id,token_id,ipfs_cid`, 896 rows) and emits
`diff_report.csv`, `media_probe.csv`, `truth-align.sql`; exit 1 on any
diff-beyond-media.
