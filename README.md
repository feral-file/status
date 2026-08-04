# status.feralfile.com

Where every published Feral File work is stored, and whether each copy
resolves right now. A static page generated from raw check data — the
public receipt for feral-file/feral-file#3435 and #3463.

## How it works

```
data/  →  build.py  →  public/
```

- `data/bitmark_exhibitions_<date>.json` — per-exhibition migration totals
  for the Bitmark-era exhibitions (bucket 3).
- `data/bitmark_chain_enumeration_<date>.csv` — every work still on the
  Bitmark chain, one row per work.
- `data/bitmark_series_media_<date>.csv` — one CDN probe per series
  (editions of a series share media files).
- `data/census/token_census_*.csv` — output of the token-health-monitor
  census (`agentic-workflows/token-health-monitor`, `--census` mode).
  Optional: until the first census lands, buckets 1 and 2 render as
  "census in progress".
- `data/updates.json` — dated changelog entries; rendered on the page and
  as `feed.xml` (RSS).

`build.py` (stdlib only, Python ≥ 3.11) cross-checks the per-work CSV
against the totals file and refuses to build on a mismatch. No number on
the page is typed by hand.

```
make build    # regenerate public/
make serve    # preview at http://localhost:8321
```

## Updating the page

1. Drop new dated data files into `data/` (the build picks the newest of
   each kind by filename).
2. Add an entry to `data/updates.json` saying what changed.
3. `make build`, review, commit, push. Deployment publishes `public/`.

## Publish-day checklist

1. Re-run the Bitmark enumeration (works in `payment`/`processing` swap
   states can flip to `complete` at any time — confirmed by Hieu,
   feral-file#3463, 2026-08-04) and drop the fresh CSVs into `data/`.
2. `make build`, review, push.

## Deployment

Cloudflare Pages (same pattern as docs.feralfile.com): build command
`python3 build.py`, output directory `public`, custom domain
`status.feralfile.com`.

## Fonts

Type roles and colors follow `feralfile-client/design/web.tokens.json`.
PP Mori is licensed and not committed here; the CSS falls back to
Helvetica until the deploy wires the hosted fonts.

## The Feral File Archive Registry

`contracts/FeralFileArchiveRegistry.sol` — the on-chain pointer to
`archive-manifest.json` (built by `tools/build_archive_manifest.py`, pinned
on the archival node). Root on Ethereum, data on IPFS — the same pattern as
the Bitmark blockchain archive.

Current manifest CID:
`bafkreihjjtrhsk5gufrnbneg2w2jwdypthbdnij5ooadzupqhq6ll3szum`

Deploy (ten minutes, Remix path):

1. remix.ethereum.org → new file → paste the contract → compile with
   0.8.24+.
2. Deploy tab → Injected Provider (the deploying wallet, Ethereum mainnet)
   → Deploy.
3. Call `setManifest("bafkreihjjtrhsk5gufrnbneg2w2jwdypthbdnij5ooadzupqhq6ll3szum")`.
4. Verify the source on Etherscan (single file, MIT, 0.8.24).
5. `transferOwnership(<Feral File Safe address>)`, then from the Safe
   (Transaction Builder) call `acceptOwnership()`.

Updating later: rebuild the manifest, `ipfs add` it on the archival node,
call `setManifest(<new cid>)` from the Safe. Every prior CID stays readable
in the `ManifestUpdated` event history.
