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
  routes through an FF host (`ipfs.bitmark.com` / `ipfs.feralfile.com` gateway on V2/V3, the
  feralfile.com API on V4/V4_2); (b) metadata documents whose media links are FF **gateway**
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
- **V4/V4_2**: `tokenURI = _baseURI() + tokenId` (OZ-style; VERIFY the live `tokenBaseURI`
  value with a real RPC — expected: the feralfile.com API). With the base URI accepted as-is
  this phase, **fixing V4 media needs no chain transactions**: regenerate the per-token
  metadata documents (media keys only) → pin → record the new CIDs in
  `artworks.metadata.ipfs_cid` (pure CID bookkeeping, phase-1 style — the API picking up the
  new documents is a consequence, not the objective; server display behavior is out of scope). (Phase 3 fact, Sourcify-verified: both contracts have
  `setTokenBaseURI(string) external onlyOwner`, so the eventual switch is one owner tx per
  contract to `ipfs://<tokenId-named-dir>/` — see Phase 3 notes.)

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
| `tools/v2-metadata-regen/audit.py` | V3: works as-is (same `tokenURI`/`artworkEditions` ABI; note V3 tokenURI has NO `/metadata.json` suffix — the cid parser needs that case). V4: new mode — the "current metadata" comes from `artworks.metadata.ipfs_cid` (DB export) fetched via gateway, not from the chain; chain read only confirms `tokenBaseURI` |
| `tools/v2-metadata-regen/gen.py` | works as-is once the export supplies (token, current doc CID, refs, medium); keys confirmed `animation_url`/`image` for V3/V4 too (server `GenerateEthereumArtworkMintingMetadata` emits the same map; still diff one live doc per series before running). Rewrite rule = phase 1 exactly: replace a media value iff it is a CDN link (`cdn.feralfileassets.com`/`imagedelivery.net`), preserve query params (`--allow-param-diff` only with code evidence), leave every other value — including FF-gateway URLs — byte-identical |
| `check-dirs.py`, `verify-media.py`, `pin.sh` | as-is |
| `tools/update-token-uri` | V3 support only this phase: gateway-check for suffix-less tokenURI; per-contract configs unchanged (base-URI extensions belong to phase 3) |
| `tools/v2-metadata-regen/gen-sql.py` | add the V4/V3 variant: `artworks.metadata.ipfs_cid` UPDATE keyed on the old value (phase-1 WHERE discipline) |

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
- Phase-1 runbooks to mirror: `tools/v2-metadata-regen/README.md` (pipeline + data policy),
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
