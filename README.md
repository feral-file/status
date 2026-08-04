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
`archive-manifest.json` (built by `tools/build_archive_manifest.py`). Root on
Ethereum, data on IPFS — the same pattern as the Bitmark blockchain archive.
Red-teamed 2026-08-04 (fresh-context adversarial audit + external passes);
history is held in contract storage, CIDs are validated on write, and the
manifest names the registry's own address so clones can't impersonate it.

Deploy runbook (rehearse the WHOLE thing on Sepolia against a test Safe
first — it retires every Transaction Builder unknown for ~nothing):

1. Compile with **exactly 0.8.24** (pragma is pinned). Note the long
   compiler version, optimizer setting + runs, and EVM version — Etherscan
   verification needs them character-exact. Remix defaults optimizer OFF.
2. Deploy from a **hardware wallet**, mainnet. Do steps 2-5 in one sitting:
   until the Safe owns the contract, the deployer key is a single point of
   failure.
3. Verify the source on Etherscan (single file, MIT, the settings from
   step 1).
4. `transferOwnership(<Feral File Safe — must already exist on mainnet>)`,
   then from the Safe (Transaction Builder) call `acceptOwnership()`
   (selector `0x79ba5097` if the ABI doesn't auto-load).
5. Confirm `owner()` = the Safe and `pendingOwner()` = zero address.
6. Write `data/registry.json`: `{"chain": "eip155:1", "address": "0x…"}`.
   Rebuild the manifest (now names its own registry), then on the archival
   node: `ipfs add -Q --cid-version 1 archive-manifest.json` — exactly those
   flags; different flags give a different CID for identical bytes.
7. From the Safe: `setManifest(<cid>)`. The Safe's first act is the
   authoritative publish.
8. Publish the address: on this page, in `status.json`, in `llms.txt` — only
   after step 5. The loop must close in both directions (page → address,
   manifest → address) or a $5 byte-identical clone is indistinguishable.

Updating later: refresh the data, rebuild, `ipfs add` with the same flags,
`setManifest` from the Safe. Every prior CID stays readable on-chain via
`historyAt(i)` — not only in event logs.

If the Safe is ever lost the contract freezes read-only at the last CID:
the intended failure mode. Assets force-sent to the contract are stuck by
design; it holds nothing.
