# CDN retirement, phase 2 — the 11,556 non-Bitmark tokens whose metadata media point at the CDN

*Drafted 2026-09-01 for the next agent. Owner: Brandon. Tracks feral-file/feral-file#3435.
Prerequisites in flight: the post-goal-2 census is running on prod-02; the IPFS node upgrades
(ff-pin-1 kubo 0.42 staging) happen before this phase starts.*

End goal (Brandon, 2026-09-01): **the artwork must exist independently of Feral File** — the
whole chain path `tokenURI → metadata document → media` resolves with no Feral File dependency.
Split across two phases (decision 2026-09-01):

- **THIS phase (2), decision 2026-09-01: exactly the Bitmark-chain treatment, applied to the
  11,556 census-`cdn`-class artworks.** In each affected token's metadata document, replace the
  **CDN media links** (`cdn.feralfileassets.com`, plus `imagedelivery.net` if it appears) with
  the `ipfs://` references — **byte-preserving everything else, query params carried over**,
  provable per token the way phase 1 proved it (`check-dirs.py`: diff = only the media keys).
  **Accepted for now, both deferred to phase 3**: (a) the token base URI in `tokenURI` still
  routes through an FF host (`ipfs.bitmark.com` gateway on V2/V3 — V4/V4_2 turned out to be
  FF-free already, see Revision 2026-09-02); (b) metadata documents whose media links are FF **gateway**
  URLs (`https://ipfs.feralfile.com/ipfs/<cid>…`) — content-addressed but FF-named — are left
  untouched this phase.
  **Hard boundary (Brandon, 2026-09-01): we do NOT touch how feralfile.com displays artwork.**
  No server/API code changes, no overlay (`alternativePreviewURI`) decisions, no site/FF1/DP-1
  work. This phase changes on-chain-reachable data only: the metadata documents on IPFS and
  (V3) the on-chain CID pointers. DB writes are the same consequential bookkeeping as phase 1 —
  when a token's metadata document gets a new CID, update the DB column that records that CID
  (`swaps.ipfs_cid` for V2-style, `artworks.metadata.ipfs_cid` for V3/V4), WHERE-pinned to the
  old value; nothing else in the DB.
- **Phase 3 (deferred)**: one comprehensive raw-document scan + fix for everything this phase
  accepts: gateway-URL media links normalized to `ipfs://`, and the per-contract base-URI
  switch so `tokenURI` itself is FF-free. Design notes captured below so nothing is re-derived.

## Where things stand (2026-09-02, end of day — supersedes the 9/01 status below)

Preconditions all met: 0.43 post-upgrade verification passed; census fresh; `nonipfs-scan`
(new tool, 2026-09-02) live-probed all 20,016 non-IPFS media URLs and found the only broken
CDN bytes — The Art of Survival ×5 thumbnails, restored at origin same day, 20,016/20,016
healthy. Since then, in one day:

**Step 0 — COMPLETE, every contract chain-audited:**
- V3 (6 contracts, 2,476 tokens): needs_fix **2,341**, exactly the census set, zero drift.
  135 Peer to Peer data-URI tokens out of scope (inline HTML anim; gateway image → phase 3).
  590 of the 2,341 carry relative image paths on chain (census can't see it; gen rule added).
- crystalline (V4_2, 9,048): all 9,048 need the fix; API==chain per token (9,048/9,048 +
  12-token live sample); ZERO overlays.
- Truth (V4, 896): chain clean, DB aligned (`<dirCID>/<tokenId>` path form), zero in-phase
  work — its 128 census-CDN rows are the filum overlay (see Pending decisions).
- Both V4 base URIs are already IPFS dirs; the V4 fix is a new dir + ONE setTokenBaseURI
  (crystalline only). Records: `step0/` base_uri_check / v4_audit_* / v3_audit CSVs.

**Step 1**: 1a sizing done — 104 units, 74,143 objects, **40.2 GB**, prod-02 projection
694/900 GB (77%), no empty prefixes. **1b mirror RUNNING** (mirror-add-pin.sh, curl-only,
self-tested) → `step1/dir_cids.csv`.

**Step 2**: DB exports done (9,944 rows, both V4 contracts). Conclusions folded into step 0;
the only align SQL remaining is crystalline's, path form, after its dir rebuild.

**Step 3**: `v4-dir-regen.py` ready + smoke-tested (byte-preserving, media keys only, query
params carried). Waiting on dir_cids. V3 gen next (audit.py already V3-capable).

**The in-pipeline fix population is exactly 11,389** (V3 2,341 + crystalline 9,048) — the
same number as the status page's "depend entirely on us" ETH class; the other 128
(Truth/filum) moved to the overlay class in Pending decisions.

**Remaining sequence**: mirror finishes → crystalline regen + V3 gen (agent) → trial series
(V3: Material Wonderland 108; crystalline is the only V4) → V3 rollout smallest-first,
~2,341 vault txs → crystalline `ipfs add -r` + 1 owner tx + path-form SQL → OpenSea refresh
→ pin-referenced rerun → census → status page rebuild.

## Pending decisions (out of phase scope — packaged 2026-09-02 for product/ops)

**The class: `alternativePreviewURI` display overlays.** Artwork-level field
(`artworks.metadata`), read by `api/swap.go`, overwrites `animation_url` AFTER the doc
fetch. Added 2024-01-22 (`08f7f0eae` "add alternative preview url to fix broken art",
extended 2024-01-29 for full URLs). It reintroduces a dependency at the display layer on
top of clean on-chain metadata — wallets following tokenURI see the clean chain path; the
API/census/status page see the overlay. Two live cases, 167 tokens:

1. **filum (Truth `0xBb12686c…`, 128 tokens) → FF CDN.** Byte-level comparison of the two
   versions (2026-09-02): all 11 files identical EXCEPT index.html, where the CDN copy adds
   `crossorigin="anonymous"` to 7 `<img>` tags (168 bytes). That attribute is load-bearing:
   `js/base.js` uses WebGL `texImage2D` + `readPixels`, and a cross-origin image without it
   taints the context → SecurityError → black screen. So in 2024-01 the artwork broke in a
   cross-origin embed, the 168-byte patch was made — and instead of repinning to IPFS and
   updating the chain pointer, the patched copy went to the CDN behind a new API field.
2. **Ten Whistlegraphs (`0x9294c5…`, 39 tokens) → aesthetic.computer.** On-chain metadata
   is all-`ipfs://` (phase-1 verified); the overlay points the display layer at the
   artist's live third-party site. Third-party dependence by (presumed) product choice.

**The question both cases reduce to: does Feral File modify an artist's source files and
pin THAT as the permanent IPFS version?** filum's fix is a 7-attribute HTML patch —
technically trivial, but it changes the artist's shipped bytes; archival integrity
(byte-canonical vs. functioning) and artist consent/credit are product calls, not pipeline
calls. The question generalizes: whenever a permanence fix requires touching the work
(crossorigin here, the 8/25 HLS→MP4 repackaging before it), who authorizes it and how is
it recorded?

Options per case:
- **filum**: (a) patch the 168 bytes into a new IPFS dir, rebuild Truth's tokenId dir, one
  `setTokenBaseURI`, drop the overlay — permanent and FF-free, rides crystalline's
  identical pipeline (the cheapest moment is now); needs artist sign-off on the patched
  bytes. (b) drop the overlay as-is — same-origin gateway serving works today, but the
  2024 failure mode (cross-origin embeds) can recur. (c) keep + reclassify on the status
  page (CDN dependency stays, honestly labeled).
- **Ten Whistlegraphs**: (a) keep the overlay, reclassify as third-party-by-choice.
  (b) drop it — the ipfs:// versions need a render test first.
- Either way the status page should stop counting overlay-only tokens the same as
  doc-level CDN tokens — different failure mode, different owner.

Owner: Sean/Hieu + (for source-file changes) the artists. The HLS precedent replaced
playlists with MP4s under operator authority — a written rule for when touching the work
is OK would close this class permanently.

## Where things stand — see STATUS.md (2026-09-04)

Current state, remaining work, and all close-out numbers live in
`ops/cdn-retirement-phase2/STATUS.md` (updated 2026-09-04): the V3 arc is
CLOSED end-to-end (2,341/2,341 chain txs + DB align + reference rows +
explicit pins), crystalline's DB align is applied ahead of its pending owner
tx, and what remains is census close-out, the #3435 checkpoint, and the unpin
backlog. The section below is the 2026-09-01 snapshot, kept as history.
Side-track closed along the way: nonipfs-scan (status PR #10) — the 5 Art of
Survival thumbnail 403s were fixed at origin 2026-09-02 and verified.

## Where things stand (2026-09-01)

- **Phase 1 (Bitmark-era) is done.** Goal 1: swap code fails closed, all 4,959 still-Bitmark
  works have preview+thumbnail `ipfs_reference` rows. Goal 2: 5,880 migrated V2 tokens on 17
  contracts re-pointed on-chain to `ipfs://` (record: `ops/bitmark-cdn-retirement/SUMMARY.md`),
  DB synced (5,905 rows), OpenSea refreshed, acceptance re-audit `needs_fix 0`.
- **Monitor fixed and deployed**: agentic-workflows #49 (census probe retries transient gateway
  failures) and #50 (universe cannot silently drop contract-held tokens; the 21 Tezos works
  recover via single-artwork refetch) merged; new census running with both.
- prod-02: kubo 0.39 sweep provider, 74,311 recursive pins, 1000 GB volume / 900 GB StorageMax,
  repo ~654 GB. `Gateway.NoFetch=true` — **everything referenced must be explicitly pinned**
  (ff-deploy#28; `tools/pin-referenced`). ff-pin-1: custody node, kubo 0.32 + roots-announce
  cron; 0.42 upgrade staged by Brandon (rollback + clone rehearsal per Sean's 8/27 conditions).
- Backlog not in this phase: unpin superseded HLS + 5,880 old V2 metadata dirs once census
  confirms nothing references them; scheduled `archive-probe`
  (needs the two independent checks Sean asked for: child bytes via public gateway + ff-pin-1
  is a provider per manifest root); Aorist onto prod-02 when displayed; second-provider pricing.

## The population (census 2026-08-25, minus phase 1's fixed set — REBUILD from the fresh census first)

This phase's population = the census `cdn`/`other` classes. The fix list is still rebuilt from
the RAW metadata documents (V3: the CID in on-chain `tokenURI`; V4: `artworks.metadata.ipfs_cid`
from a DB export) — the API overlays/rewrites and is never authoritative (phase-1 lesson) — but
the classification rule is narrow: **a media key needs fixing iff it points at
`cdn.feralfileassets.com` (or `imagedelivery.net`)**. FF-gateway media links are out of scope
until phase 3 (which will scan every raw document once and normalize scheme + base URI together;
the census `ipfs_gateway` class — 21,813 rows on 8/25 — is the starting estimate for that scan).

**Number reconciliation** (the older docs disagree; computed 2026-09-01 from both censuses):
`17,261` (8/3 issue comment) and `17,247` (phase-1 plan's out-of-scope note) are the ALL-ETH
"no content-addressed media at all" totals (8/3: 11,389 non-Bitmark + 5,872 Bitmark-era
migrated; 8/25: 11,389 + 5,864 = 17,253) — the phase-1 note mislabeled that total as
"non-Bitmark", double-counting the ~5.9k tokens phase 1 itself fixed. The non-Bitmark
population has been ~11.4-11.5k all along.

As of census 2026-08-25: 11,556 tokens, **all Ethereum** (Tezos: 5,320 works, zero CDN-class).
22,625 `cdn`/`other` media rows: 22,586 on `cdn.feralfileassets.com`, 39 on
`aesthetic.computer`. By exhibition:

| tokens | exhibition | contract | version |
|---|---|---|---|
| 9,048 | crystalline work (46a0f68b) | 0xBE0A4E26a156B2a60cF515E86b3Df9756DEE1952 | V4_2 |
| 669 | I KNOW – On the aesthetic of truth (99aa32cb) | 0xE46A41b840176b62983FC71162dc9faEAC4D9bcB | V3 |
| 611 | Peer to Peer (48a442ae) | 0x2A86C5466f088caEbf94e071a77669BAe371CD87 | V3 |
| 600 | Chain Reaction (484087f9) | 0xc4f0ee96676D3de800b9725eb628DE1C5a0CBea1 | V3 |
| 182 | BOOM TOWN (24e7d8fd) | 0x6003994adECA13407E8dbEE808280CC3EF2ab820 | V3 |
| 171 | Gray Matter (77de6645) | 0x6e82e4B398Ca4137007ba69ddD6FF699334d13b5 | V3 |
| 128 | Truth (6d5ee1fb) | 0xBb12686c360e9057be3CD031140035A705e19ceC | V4 |
| 108 | Material Wonderland (8bf192b1) | 0x8f30722dd16BD63cF2665C383c1aEf5e307B0046 | V3 |
| 39 | Ten Whistlegraphs (56049bb2) | 0x9294c5787f5BC7462E991fE8B6FeaC75F433ac39 | V2 (special, see below) |

**Ten Whistlegraphs (39)** is not a chain problem: phase 1 verified those tokens' on-chain
metadata is all-`ipfs://`; the census sees `aesthetic.computer` because the API overlays
`artwork.metadata.alternativePreviewURI`. Third-party-dependence by product choice → needs a
product decision (keep the overlay and reclassify on the status page, or drop the overlay),
not a migration. Exclude from the pipeline below.

**The pin units are small.** The 22,586 CDN URLs collapse to **~104 distinct CDN directories**
(`previews|thumbnails/<uuid>/<ts>/`): crystalline work = **1 directory** shared by all 9,048
tokens (`nft.html?hourIdx=N` + per-token `generated_images/crystal_N_img.jpg`), Truth = 1,
Material Wonderland = 17 (video, sampled ~360 MB each ≈ 6 GB), Peer to Peer = 26, etc.
Software previews are directories — size them at the origin bucket (HEAD on the CDN only sees
index.html); expect low-tens of GB total unless crystalline's generated_images surprises.
prod-02 has ~250 GB headroom under the current StorageMax.

## Mechanism — verified from feral-file-server source (2026-09-01)

How metadata is served (`GET /api/contracts/<addr>/tokens/<id>`, `api/swap.go getEthTokenMetadata`):

- **All versions serve the metadata JSON from IPFS**: V2 from `swaps.ipfs_cid`, V3/V4/V4_2/…
  from `artworks.metadata.ipfs_cid` (`IpfsGatewayGet`). The CDN URLs live INSIDE those pinned
  per-token `metadata.json` documents. The API then rewrites `ipfs://` → gateway and overlays
  `alternativePreviewURI` — same reason the census is not authoritative; **build fix lists from
  the chain (V3) or from the metadata docs themselves (V4)**.
- **V3 contracts are V2-shaped on chain**: `tokenURI = _tokenBaseURI + artworkEditions[tokenId].ipfsCID`
  (no `/metadata.json` suffix, unlike V2) and the SAME `updateArtworkEditionIPFSCid(tokenId, cid)`
  guarded by trustee/owner (Sourcify-verified on I KNOW's contract). → fixing V3 media requires
  one on-chain tx per token (~2,441 tokens ≈ 0.14 Ggas ≈ 0.03 ETH at 0.2 gwei).
- **V4/V4_2**: `tokenURI = _baseURI() + tokenId` (OZ-style). **SUPERSEDED 2026-09-02 — the
  RPC check this bullet asked for was run and falsified the assumption; see "Revision
  2026-09-02" below.** The live base URI is NOT the feralfile.com API: both contracts
  already point at an IPFS directory of tokenId-named docs, so the V4 fix is a new
  directory + ONE `setTokenBaseURI` owner tx per contract, and the authoritative fix list
  comes from the on-chain directory, not a DB export.

**Approach decision (Brandon, 2026-09-01): do this with clean, reusable LOCAL tools, phase-1
style** — fetch → byte-preserving rewrite → check → pin → vault-signed txs with
preflight/trial/check — NOT the server's `PatchSeriesOnchainMetadata` workflow. Reasons: the
phase-1 discipline (only the media keys change, provable with `check-dirs.py`-style
verification; every step leaves a csv record in `ops/`) and the server regen is NOT
byte-preserving (it rebuilds the whole document from current DB — description/royalty drift
would be unreviewable at this scale).

Server-side pieces still used, deliberately small:
- `EnsureIPFSReferenceByURI` (or reviewed SQL) for the `ipfs_reference` rows — same as phase 1's rule.
- back-office `refreshOpenSeaTokensMetadata` — the same single-task OpenSea refresh as phase 1.
- For reference only: `PatchSeriesOnchainMetadata` / `GenerateArtworkTokenMetadata`
  (`internal/tasks/patch_series_onchain.go`, `opensea.go`) exist and prefer `ipfs_reference`
  rows when set — useful to cross-check our regenerated documents, not to run.

**Tools to build/extend (all in `tools/`, logic only; run data goes to `ops/`):**

| tool | change |
|---|---|
| `tools/metadata-regen/audit.py` | V3: works as-is (same `tokenURI`/`artworkEditions` ABI; note V3 tokenURI has NO `/metadata.json` suffix — the cid parser needs that case). V4: new mode — the "current metadata" comes from `artworks.metadata.ipfs_cid` (DB export) fetched via gateway, not from the chain; chain read only confirms `tokenBaseURI` |
| `tools/metadata-regen/gen.py` | works as-is once the export supplies (token, current doc CID, refs, medium); keys confirmed `animation_url`/`image` for V3/V4 too (server `GenerateEthereumArtworkMintingMetadata` emits the same map; still diff one live doc per series before running). Rewrite rule = phase 1 exactly: replace a media value iff it is a CDN link (`cdn.feralfileassets.com`/`imagedelivery.net`), preserve query params (`--allow-param-diff` only with code evidence), leave every other value — including FF-gateway URLs — byte-identical |
| `check-dirs.py`, `verify-media.py`, `pin.sh` | as-is |
| `tools/update-token-uri` | V3 support only this phase: gateway-check for suffix-less tokenURI; per-contract configs unchanged (base-URI extensions belong to phase 3) |
| `tools/metadata-regen/gen-sql.py` | add the V4/V3 variant: `artworks.metadata.ipfs_cid` UPDATE keyed on the old value (phase-1 WHERE discipline) |

## Revision 2026-09-02 — measured V4 reality (step 0 run; supersedes the V4 mechanism above)

`check-base-uri.py` (RPC, Brandon) + `v4-dir-audit.py` (gateway) measured what the plan had
assumed. Facts:

- **Both V4-family base URIs are ALREADY IPFS directories** (`ipfs://<dirCID>/<tokenId>`,
  entries named by full decimal tokenId):
  - Truth `0xBb12686c…` → `ipfs://QmQjzvrvZjzNGiqQhTGsiHeTpb9FmEcjCVWxVySf5FANC1/` (896 entries)
  - crystalline `0xBE0A4E26…` → `ipfs://QmY67Gq1514Zj1yWtHxoHeoVj8FpFLM5ZNSNQejjirxKTo/` (9,048 entries)
  The phase-3 `setTokenBaseURI` switch already happened for these contracts at some point —
  the V4 **link layer is FF-free today**; what can still be dirty is the doc contents.
- **Truth needs NO metadata fix, NO tx — and (corrected 2026-09-02, after the DB export)
  NO DB align either.** All 896 on-chain docs' media are `ipfs://` (audit:
  `v4_audit_truth.csv`, chain_needs_fix 0), and the export showed
  `artworks.metadata.ipfs_cid` = `<dirCID>/<tokenId>` for every token — the DB points INTO
  the same on-chain directory; there is no stale doc pointer. (The earlier "DB drift"
  reading was wrong: it checked `alternativePreviewURI` at the SERIES level, which is null.)
  The census's 128 CDN-class Truth rows come from the **per-ARTWORK
  `alternativePreviewURI` overlay**: api/swap.go's V3+/V4 branch captures
  `art.Metadata.AlternativePreviewURI` and overwrites `animation_url` after the doc fetch
  (`FIXME temporary solution to support broken art on OpenSea`); relative values get the
  CDN host via `thumbnail.GetPreviewURL`. Evidence: filum #1's API animation ts
  (1706081014) matches neither the chain doc (ipfs) nor `preview_uri` (1695225066).
  CONFIRMED by `step2/export-v4-overlay.sql` (run 2026-09-02): exactly 128 overlay rows,
  all filum, all `previews/71e2bed5…/1706081014/index.html?…`; **crystalline has ZERO
  overlays** (its post-rebuild API path is unobstructed). That puts Truth's 128 in the
  SAME class as Ten Whistlegraphs — an overlay/product decision, explicitly out of this
  phase's hard boundary ("no overlay decisions") — the chain path a wallet follows is
  already clean. Status-page classification is where it surfaces, not this pipeline.
- **DB convention learned from the export (matters for crystalline's SQL):**
  `artworks.metadata.ipfs_cid` on V4 contracts holds a PATH `<dirCID>/<tokenId>`, not a
  bare doc CID (`IpfsGatewayGet` fetches it as-is). So crystalline's post-rebuild
  bookkeeping is: set `ipfs_cid = '<newDirCID>/<tokenId>'` WHERE it still equals
  `'<oldDirCID>/<tokenId>'` — the same single dir root across all 9,048 rows, WHERE-pinned
  per token.
- **crystalline is the real V4 fix**: audit `v4_audit_crystalline.csv` — 9,048/9,048 on-chain
  docs carry CDN media (image + animation_url), full population coverage, none missing.
  Per-token API-vs-chain media URLs compared 2026-09-02: 9,048/9,048 identical — no
  Truth-style drift signal. Still owed before its DB-align SQL: the CID-level check
  (`artworks.metadata.ipfs_cid` vs the dir entry's doc CID, from a DB export — same
  discipline as Truth; the UPDATE's WHERE pins the DB's own value either way, and any
  CID mismatch found gets the old-vs-chain doc diff before inclusion).
  Pipeline: fetch all 9,048 docs from the on-chain dir (authoritative source — not the DB) →
  byte-preserving media-key rewrite → build ONE new directory with entries named by full
  decimal tokenId → pin on prod-02 → **one `setTokenBaseURI("ipfs://<newDir>/")` tx**
  (onlyOwner — owner() recorded by check-base-uri.py; confirm the vault holds that key) →
  align `artworks.metadata.ipfs_cid` to the new doc CIDs (bookkeeping) → OpenSea refresh.
  Compatibility check before the tx: render one token from the new dir path on
  OpenSea/indexer staging the way phase 3 planned it.
- Consequences for the tools table: `audit.py`'s planned "V4 mode reading the DB export" is
  replaced by `v4-dir-audit.py` (chain-dir-driven); `gen.py` consumes the audit CSV;
  `gen-sql.py`'s V4 variant now aligns DB → chain (Truth) or DB → new dir (crystalline).
- V3 mechanism unchanged (verified same run: all six V3 contracts answer
  `https://ipfs.bitmark.com/ipfs/<bare CID>`; per-token `updateArtworkEditionIPFSCid` stands
  — note the V3 gateway host is ipfs.bitmark.com, not ipfs.feralfile.com as the
  acceptance bullet above guessed).
- **V3 full-contract chain audit (2026-09-02, `v3_audit.csv`, 2,476 tokens): needs_fix
  2,341 — EXACTLY the census set, zero drift in either direction.** Single base URI across
  all six contracts; trustee/owner per contract in `v3_audit.contracts.csv`; no legacy-format
  tokens. Two findings beyond the counts:
  - **135 Peer to Peer tokens have `data:application/json;base64` tokenURI** (fully inline
    on-chain metadata): `animation_url` is inline `data:text/html` (FF-free), `image` is an
    FF-gateway URL — no CDN anywhere, so out of phase-2 scope; the gateway-named image is
    phase-3's normalization class.
  - **590 of the 2,341 carry RELATIVE image paths on chain**
    (`previews/<uuid>/<ts>/_unique-thumbnails/N-large.jpg`, no scheme/host) — the API
    prefixes the CDN host when serving, so the census showed full URLs; on chain these are
    unresolvable for any wallet. All 590 fall inside `_unique-thumbnails/` subtrees of
    preview dirs already in the 104-unit mirror list (13 dirs). The gen rewrite rule must
    treat a relative `previews/…`/`thumbnails/…` value as a CDN link (implied host) and
    rewrite it to `ipfs://<unitCID>/<subpath>`. Related: the server's own IPFS uploads
    historically EXCLUDED `_unique-thumbnails` (`internal/infra/ipfs/ipfs.go` exclusion
    regex) — the phase-2 mirror deliberately includes them.
  With crystalline (9,048, all needs_fix) and Truth (896, none) audited on 9/02 as well,
  every phase-2 contract now has a chain-authoritative fix list; the 104-unit mirror list is
  final (chain CDN URL coverage: 100%; only crystalline's own dir and Truth's drift dir are
  not referenced by V3 docs, both accounted for).

## The plan

0. **Preconditions**: node upgrades done; fresh census merged; rebuild this doc's population
   table from it (`fixed-by-goal2` filter: `ops/bitmark-cdn-retirement/result.csv`).
1. **Bytes to IPFS (per series)**: enumerate the ~104 CDN dirs from the census URLs
   (`previews|thumbnails/<uuid>/<ts>/` prefixes); size them at the origin bucket; mirror each
   dir → `ipfs add -r --cid-version 0` on prod-02 (tunnel), pin; verify a sampled file via
   `ipfs.feralfile.com` AND one public gateway. Watch prod-02 headroom (StorageMax 900 GB).
2. **Reference rows**: per artwork, `preview_uri`/`thumbnail_uri` → `ipfs_reference` rows
   pointing at `ipfs://<dirCID>/<path>` with the original query params preserved
   (crystalline: `ipfs://<cid>/nft.html?hourIdx=N` per token — same pattern phase 1 preserved).
   Prefer the server's ensure-reference tasks; verify row shape against a Bitmark-era row.
3. **Trial series** (smallest, one per version): Material Wonderland or BOOM TOWN for V3;
   Truth for V4. Pipeline per series, phase-1 shape: audit (chain for V3 / DB-doc for V4) →
   gen (byte-preserving, only media keys) → check-dirs → verify-media → pin →
   V3: `update-token-uri` preflight → `run-all --limit 1` → Etherscan/gateway check → run-all →
   check; V4: regen dirs pinned → `artworks.metadata.ipfs_cid` SQL (CID bookkeeping,
   WHERE-pinned to the old CID, expect UPDATE 1 per row).
4. **Rollout** remaining series smallest-first, crystalline work (9,048) last. V3 txs are
   local vault-signed like phase 1 (gas ceiling, nonce windows, quiet-window check on `eth_tx`
   for the trustee before each contract).
5. **Pin + measure**: `tools/pin-referenced` with a fresh DB export (the referenced-CID set just
   grew); OpenSea refresh per contract (back-office `refreshOpenSeaTokensMetadata`, single task,
   1s pacing); census on prod-02; status page rebuild — ETH `dependent` should approach 0,
   leaving only the third-party class (Ten Whistlegraphs + any others the fresh census shows).
6. Update this doc + `SUMMARY.md`-style record in `ops/` (tools/ holds only reusable logic).

## Phase 3 (deferred by decision 2026-09-01): gateway-URL media links + the link layer

Everything verified so far, so the next phase starts from facts, not archaeology:

- **Comprehensive raw-document scan**: fetch every token's actual metadata document (V2/V3 from
  the chain CID, V4 from `artworks.metadata.ipfs_cid`, Tezos from token_metadata) and classify
  every media value strictly by scheme. Fix list = anything not `ipfs://…` — chiefly the FF
  gateway URLs this phase leaves untouched (census `ipfs_gateway` class: 21,813 rows on 8/25 as
  the starting estimate; the census can't see which of those are baked into documents vs
  API-rewritten, hence the raw scan). Same byte-preserving treatment, same tools.

- V2: `setTokenBaseURI("ipfs://")` (trustee-authorized; empty falls back to `ipfs://` too);
  tokenURI becomes `ipfs://<cid>/metadata.json`. Phase-1 dirs already resolve publicly —
  unblocked whenever the decision lands. `tools/update-token-uri base-uri-tx` exists but
  validates `https://<gw>/ipfs/`; relax to `ipfs://`.
- V3: same switch (verify setter auth); tokenURI appends the bare CID (no `/metadata.json`).
- V4/V4_2: build ONE directory per contract with entries named exactly `tokenId` in decimal
  (contract appends `tokenId.toString()`, nothing else), pin, then one
  `setTokenBaseURI("ipfs://<dirCID>/")` — **onlyOwner**: read `owner()` and confirm the vault
  holds that key (phase-1 V2 owners were `0x1d05cf6c6beb0c869851bfdb9510d4e44e855ad6`).
- Per-contract compatibility verification (OpenSea/indexer render one token before+after, then
  refresh); note a base switch freezes delivery to the pinned snapshot — future metadata edits
  then need a new dir (V4) or per-token CID updates (V2/V3).
- Sequencing note: the superseded-metadata unpin backlog interacts with V2's switch (old dirs
  stay referenced by tokenURI until then only via `swaps.ipfs_cid` history — re-derive the
  reference set before unpinning).

## Working notes

- `tools/pin-referenced`, `tools/census-rescan`, `tools/archive-probe`: unchanged, use as in phase 1.
- Phase-1 runbooks to mirror: `tools/metadata-regen/README.md` (pipeline + data policy),
  `tools/update-token-uri/README.md` (vault signing, quiet window, trial-first),
  `ops/bitmark-cdn-retirement/SUMMARY.md` (what a finished phase record looks like).
- RPC notes: 1rpc.io free tier exhausted this week; publicnode/flashbots DNS-blocked on this
  network; use Infura (`MAX_GAS_GWEI`-style pacing already in the tools). Sourcify works for
  contract source. Back-office reachable only via `make feralfile-back-office ENV=prod HOST=prod-01`.

## Out of scope, recorded

- `alternativePreviewURI` third-party works (product decision).
- Tezos: nothing to do for media (0 dependent). The Tezos metadata-link layer (what FA2
  token_metadata points at for the migrated + native contracts) has not been audited under the
  new no-FF-dependency goal — audit it the same way (expectation: `ipfs://` already, since the
  HLS fix wrote ipfs links via `update_edition_metadata`; verify, don't assume).
- The status page's claim boundary will need extending once phase 3 ships: today it measures
  the artwork-media layer only; the metadata-link layer then becomes a measurable claim too
  (feed it into the census/monitor as a new check).
