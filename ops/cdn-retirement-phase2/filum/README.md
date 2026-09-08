# filum fix — Truth `0xBb12686c360e9057be3CD031140035A705e19ceC` (V4), 128 tokens

*Prepared 2026-09-08 (Brandon). Part of CDN-retirement phase 2, feral-file/feral-file#3435.
Decision context: `ops/cdn-retirement-phase2.md` § Pending decisions (option a).
State 2026-09-08: steps 1–3 DONE (pinned, render-checked, DB measured + align SQL generated);
step 4 (chain tx) gated on the artist; step 5 is `filum-align.sql` (896 `ipfs_cid` swaps only —
the display overlay stays, decision 2026-09-08), apply only after 4.*

## What is wrong, measured

- On chain, every filum doc already points `animation_url` at an IPFS artwork dir
  (`ipfs://Qma2VZ…?edition_number=…&…`, 128/128) and `image` at a per-token IPFS CID. The
  base dir `QmQjzv…` holds 896 docs (7 series × 128); filum is the only series affected.
- The API overlays `animation_url` with the CDN copy
  (`artworks.metadata.alternativePreviewURI`, per token, same query params). That overlay is
  the whole reason the census counts filum as CDN-dependent.
- The CDN copy vs the IPFS dir, every file byte-compared (`art_compare.csv`, 11 files incl.
  `js/base.js`, `js/manifest.edn`): **10 identical; index.html differs only by
  `crossorigin="anonymous"` on the 7 hidden `<img>` tags, 168 bytes** (`index.html.diff`).
  The attribute is load-bearing (WebGL `readPixels` on a cross-origin image taints the
  canvas → black screen), which is why the 2024 patch was made — but it went to the CDN
  behind the overlay instead of to IPFS + a chain pointer update.

## The fix, built and proven locally (`tools/metadata-regen/filum-build.py`)

| | old | new |
|---|---|---|
| artwork dir (animation_url target) | `Qma2VZMhsrMjrbCZcJQXuF71XTwRdL45EPH97KC8BHo8Pd` | `QmQ8qYSYNdiWR5Pjgqudnckf2Mk2R7mkK8T4L12Q3rnCWV` |
| base dir (tokenBaseURI) | `QmQjzvrvZjzNGiqQhTGsiHeTpb9FmEcjCVWxVySf5FANC1` | `QmZTedFYmyhEH7G77BTnuVk7DHrYWJzdHaWK4wMeXwkPVo` |

Proofs the tool enforces (it exits non-zero otherwise):
1. The inputs are the real thing: the fetched IPFS bytes re-add (`ipfs add -r --cid-version 0`,
   offline) to exactly `Qma2VZ…` and `QmQjzv…` — so the same flags on prod-02 yield the
   recorded new CIDs.
2. Patched index.html = IPFS index.html with the attribute inserted into exactly 7 `<img>`
   tags, and that result is byte-equal to the CDN's index.html. Every other file is
   byte-identical across IPFS, CDN and the new dir. So the new artwork dir is **exactly the
   version collectors have been seeing since 2024**, now content-addressed.
3. The 128 docs change only the artwork CID inside `animation_url` (query params untouched):
   reverse-substitution reproduces the original bytes; JSON-equal on every other key. The
   other 768 docs are byte-identical. Per-token old→new doc CIDs: `doc_updates.csv`.

Reproduce from scratch (fetches everything from ipfs.feralfile.com + the CDN, ~2 min; needs
the raw dir blocks decoded via local kubo — the fetchers do that with `ipfs --offline`):
```
S=<scratch>
python3 tools/metadata-regen/filum-fetch-art.py  $S    # → $S/art-ipfs, $S/art-cdn, art_compare.csv; asserts the dir CID reproduces
python3 tools/metadata-regen/filum-fetch-docs.py $S    # → $S/truth-src (896 docs); asserts every doc CID + the base dir CID reproduce
python3 tools/metadata-regen/filum-build.py --art-ipfs $S/art-ipfs --art-cdn $S/art-cdn --truth-src $S/truth-src --out ops/cdn-retirement-phase2/filum
```
(`filum-fetch-docs.py` expects `$S/QmQjzv….links.csv`, the decoded base-dir listing —
`ipfs --offline block put` the `?format=raw` block, then `ipfs --offline dag get`.)
`build/` (7.4 MB: `art-new/`, `base-new/` 896 docs) is gitignored — regenerate with the command above.

## Gate

**The artist's sign-off on the patched bytes** (Feral File pinning a modified index.html as
the permanent version). Sean is asking the artists (#3435, 2026-09-04). Steps 1–3 below
are reversible prep and can run before it; step 4 (the chain tx) waits for it.

## Operator steps (in order)

1. **Pin on prod-02 — DONE 2026-09-08** (`pin-and-verify.sh` green: both CIDs reproduced by
   prod-02's `ipfs add`, recursive pins present, gateway 200 on index.html / js/base.js / a
   base-dir doc, served index.html carries the 7 attributes). Command, for the record:
   ```
   make ipfs-port-forward ENV=prod HOST=prod-02          # in ff-deploy
   ops/cdn-retirement-phase2/filum/pin-and-verify.sh     # adds both dirs, asserts CIDs == cids.csv, checks gateway 200 + 7 attrs
   ```
   Unpin is the rollback (`ipfs pin rm` both new CIDs) if the fix is abandoned.
2. **Render check — DONE 2026-09-08** (`render-check/`): the new dir's index.html opened in
   Chrome with the token's query params draws the piece on a WebGL canvas exactly like the
   CDN copy collectors see today (same frame at the same elapsed time), all 7 `<img>` loaded
   with `crossorigin="anonymous"`, zero page-side console errors; the unpatched old IPFS dir
   behaves the same when opened same-origin, as expected (the taint only bites cross-origin).
   Original instruction, kept: open
   `https://ipfs.feralfile.com/ipfs/QmQ8qY…/index.html?edition_number=0&artwork_number=1&blockchain=ethereum&contract=0xBb12686c360e9057be3CD031140035A705e19ceC&token_id=2439046679443273982118864381573244666655869184&token_id_hash=0x24549d9c4200fb1c06d243fff577cb323640f16ab4352a8e0f0fcf30fa91f572`
   in a browser and, embedded cross-origin (e.g. from feralfile.com's viewer), confirm it draws
   rather than a black canvas — that is the failure mode the patch exists for.
3. **DB export — DONE 2026-09-08** (`export-truth-db.sql` → `truth_db_export.csv`, 896 rows,
   gitignored as a DB export). Measured: **all 896 `ipfs_cid` are path-form
   `QmQjzv…/<tokenId>`** (the 2026-09-02 "older generation" worry does not apply — DB and
   chain already agree); the 128 filum rows carry `alternativePreviewURI` stored as the
   RELATIVE key `previews/71e2bed5…/1706081014/index.html?<params>` (the API prefixes the
   CDN host), and every one's query string equals its on-chain `animation_url`'s (0
   mismatches); the other 768 rows have no overlay. `filum-align.sql` is generated from it:
   **896 `ipfs_cid` path swaps only**, each WHERE-pinned to the exact current value.
   **Decision 2026-09-08 (Brandon): the `alternativePreviewURI` overlay is NOT touched** —
   the goal is chain alignment (tokenURI → permanent, self-contained IPFS version), not
   changing how feralfile.com displays the piece. `gen-filum-sql.py --drop-overlay` still
   exists if that is ever wanted. Consequence to keep in mind: the API (and therefore the
   census/status page) will keep seeing the CDN overlay for these 128, so they stay in the
   overlay class on the page — reclassify there rather than counting them as CDN-dependent docs.
4. **Chain tx** (after sign-off): `tools/update-token-uri/v4-base-uri.config.filum.example.json`
   → `v4-base-uri.config.json`, then `preflight` → `tx` → vault sign → `broadcast`, exactly as
   `RUNBOOK-crystalline-base-uri.md` (same owner `0x1d05cf6c…`, same tool, ~50k gas).
5. **DB align** (after the tx) — `filum-align.sql` is READY (generated 2026-09-08; regenerate
   from a fresh export if anything on Truth changes first):
   ```
   psql "<back-office>" -v ON_ERROR_STOP=1 -f ops/cdn-retirement-phase2/filum/filum-align.sql | sort | uniq -c   # dry-run: expect 896 × "UPDATE 1"
   { cat ops/cdn-retirement-phase2/filum/filum-align.sql; echo 'COMMIT;'; } | psql "<back-office>" -v ON_ERROR_STOP=1 | sort | uniq -c
   ```
   Any count other than 896 → ROLLBACK and re-export. After this the DB's `ipfs_cid` matches
   the new on-chain base dir for all 896 Truth tokens; wallets following `tokenURI` get the
   patched, self-contained IPFS version. feralfile.com's display path is unchanged.
6. **No OpenSea refresh** is needed for this contract (tokenURI-direct, same as crystalline;
   the refresh hold in STATUS.md still applies). Re-derive the reference set + pin-referenced
   afterwards if `ipfs_reference` rows point at the old artwork dir.
7. Census rerun is deferred to the single close-out run (STATUS.md).

## Files

- `cids.csv` — the four CIDs above
- `doc_updates.csv` — 128 rows: token, old/new doc CID, old/new `animation_url`, `image`
- `index.html.diff` — the exact 168-byte patch
- `art_compare.csv` — per-file IPFS-vs-CDN byte comparison (11 files)
- `pin-and-verify.sh` — operator step 1
- `export-truth-db.sql` — operator step 3 (export is gitignored)
- `filum-align.sql` — operator step 5, generated 2026-09-08 (896 WHERE-pinned `ipfs_cid` UPDATEs; overlay kept)
- `../../tools/metadata-regen/filum-build.py` — the builder (all proofs)
- `../../tools/db-align-sql/gen-filum-sql.py` — operator step 5
- `../../tools/update-token-uri/v4-base-uri.config.filum.example.json` — operator step 4
