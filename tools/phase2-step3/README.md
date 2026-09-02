# phase2 step 3 (V4/V4_2) — rebuild the tokenId-named metadata dir

See the docstring of `v4-dir-regen.py`. Byte-preserving media-key rewrite of
the on-chain docs (crystalline: 9,048), driven by step 1b dir_cids.csv.
Smoke-tested 2026-09-02 on 3 tokens: only image/animation_url change, query
params preserved (incl. image ?variant=small), all other bytes identical.
After regen: ipfs add -r --hidden --cid-version 0 via the tunnel, ONE
setTokenBaseURI("ipfs://<newDir>/") owner tx, then DB align to the new doc
CIDs (add -r without -Q lists per-file CIDs).

## Full step-3 toolchain (added 2026-09-03, while the step-1b mirror ran)

Execution order once `step1/dir_cids.csv` exists:

| # | tool | who | does |
|---|---|---|---|
| 1 | `v3-doc-regen.py` | agent | 2,341 V3 docs: fetch by on-chain CID, byte-preserving media rewrite — full CDN URLs AND the 590 relative `previews/…` paths → `ipfs://<unit>/…`; emits per-contract doc files + `plan.csv` |
| 2 | `v4-dir-regen.py` | agent | crystalline's 9,048 dir docs (already smoke-tested) → new tokenId-named dir |
| 3 | `pin-docs.py` | operator (tunnel) | uploads V3 docs to prod-02 (MFS batch, resumable), pins, emits `updates_<contract>.csv` for update-token-uri |
| 4 | `mfs-batch-add.py` | operator (tunnel) | uploads crystalline's new dir → newDirCID (then pin via mirror flow or pin/add) |
| 5 | `../update-token-uri` (`docSuffix: ""` configs) | operator (vault) | V3: preflight → run-all, ~2,341 `updateArtworkEditionIPFSCid` txs, smallest contract first |
| 6 | `../update-token-uri/v4-base-uri.mjs` | operator (vault) | crystalline: ONE `setTokenBaseURI("ipfs://<newDir>/")` owner tx (preflight checks owner, samples, new-dir servability) |
| 7 | `gen-v4-sql.py` | operator (back-office) | crystalline DB align: path-form `<dir>/<tokenId>` UPDATEs, WHERE-pinned + series anchor — run only AFTER the tx |
| 8 | `../phase2-step2/gen-reference-sql.py` | operator (back-office) | `ipfs_reference` upserts for all phase-2 artworks (needs `step2/export-v3-tokens.sql` run first); conflicts/unmapped go to review CSVs, never clobbered |

All regen paths smoke-tested against live docs with a fake dir-CID map:
relative `_unique-thumbnails` images, dir-URL+query animations, bare-file
thumbnails, and in-dir files all rewrite correctly; non-media bytes proven
identical.
