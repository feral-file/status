# Special-project contracts — media dependency + OpenSea collection uuid

*Started 2026-09-08 (Brandon). Track opened by OpenSea's 2026-09-04 audit
(`ops/opensea-metadata-path/ryan_reply_2026-09-04.md`): 57 collections on their side belong
to contracts we deployed from the deployer address but never published as an exhibition.
Two questions, one population: (a) does their media depend on the CDN? (b) how does their
`collection_uuid` get pinned? This directory answers (a) and enumerates the population for (b).*

## Definition (from the server, `api/swap.go`)

A "special-project" contract is one where `exhibition_contract` has no row for the address
and `owner() == opensea.deployer_address` (`0x1d05cf6c6BEb0c869851BFdb9510D4E44E855ad6`).
For those, the API reads `tokenURI` on chain, fetches the doc from IPFS, rewrites `ipfs://`
to our gateway, and derives `collection_uuid = uuid5(ns, doc.collection_name)` per token.
No DB rows exist for these tokens → none of the phase-2 tooling (census pin units,
`ipfs_reference`, regen) has ever looked at them, and **the census universe cannot see
them by construction** (token-health-monitor walks FF-API exhibitions → exhibition-contracts
→ artworks; `discovery.py`).

## Population — how it was built

1. **Ryan's list** (`opensea_ff_collections_full_2026-09-04.csv`, categories 2/3/7 = 81 rows)
   carries **no contract addresses** for this class (`eth_contracts` empty).
2. **OpenSea collection pages** (`tools/opensea-slug-contracts.py` → `slug_contracts.csv`): the
   page HTML embeds the collection's contract. Yield: 21 real-looking addresses; 41 pages
   only carried template noise (`0x4200…0006`, OP-stack WETH) and 19 returned 404 (the
   unbound/auto-created ones). **Of the 21, only 8 exist on Ethereum mainnet** — the other
   13 have no code at `latest` (`zero_token_contracts_chain.csv`), so those OpenSea
   collections are either on another chain or the page's most-mentioned address is not the
   collection contract. Not ours on mainnet either way.
3. **The indexer** (`indexer-v2.feralfile.com/graphql`) is registry-driven by
   `deployer_addresses` (ff-deploy `ansible/app_defaults/indexer/registry/publisher.json`),
   so everything deployed from `0x1d05cf6c…` should be in it under publisher "Feral File".
   `tools/indexer-walk.py` walks the whole Ethereum index (light fields, 255/page) into
   `indexer_universe.csv` (gitignored, ~250-400k rows across all publishers); the derived
   per-contract table is `indexer_contracts_feralfile.csv` (see below once the walk lands).
   Note the registry's `collection_addresses` list (53) is exactly the platform set — it
   adds nothing for this class.

## Media audit — the 8 mainnet special-project contracts (2026-09-08)

`tools/audit-contracts.py` pulls every token per contract from the indexer with the raw
on-chain doc (`metadata.origin_json`) and classifies `image` / `animation_url` by host.

| collection (OpenSea slug) | contract | tokens | media |
|---|---|---|---|
| a2p-v1 | `0x3892f76b…` | 346 | all `ipfs://` |
| a2p-v2 | `0xc3ecd59b…` | 519 | all `ipfs://` |
| machine-hallucinations-coral-artificial-reef | `0x7acc33c0…` | 66 | all `ipfs://` |
| machine-hallucinations-coral-generative-ai-data-painting | `0x4ce2b581…` | 53 | all `ipfs://` |
| the-adventures-of-minoriea (Auriea Harvey) | `0xdb8acab6…` | 4 | all `ipfs://` |
| take-over-miami (Reisinger) | `0xbcb540b5…` | 2 | all `ipfs://` |
| self-contained (Entangled Others) | `0x6b7f2e36…` | 1 | all `ipfs://` |
| social-sacrifice (DRIFT) | `0xb1676ce8…` | 1 | all `ipfs://` |

**992 tokens, 0 on `cdn.feralfileassets.com` / `imagedelivery.net`, 0 third-party, 0 burned.**
662 docs have `image` + `animation_url`, 330 have `image` only. Every doc carries a
`collection_name` (this is what the API hashes into `collection_uuid`).

**Resolvability** (`media_cid_probe.csv`): the 227 distinct media CIDs behind those 992
docs — **227/227 served by `ipfs.feralfile.com` (prod-02, `NoFetch`, so 200/206 means
locally present)** and 226/227 by `ipfs.io` (one transient 504). So this class is not
CDN-dependent and is already pinned on our serving node; nothing to repoint.

Caveat: these are the on-chain docs. Whether the CIDs are *explicitly pinned* on prod-02
or only cached (the 2026-08-28 finding for platform tokens) is not distinguished by a
gateway probe — fold them into the next `tools/pin-referenced` run (they are not in the DB
export that tool starts from, so give it this directory's CID list).

Records: `special_project_tokens.csv` (992 rows), `special_project_summary.csv`,
`media_cid_probe.csv`, `candidate_contracts.csv`, `zero_token_contracts_chain.csv`.

## Open

- **Population completeness**: the indexer walk (`indexer_universe.csv` →
  `indexer_contracts_feralfile.csv`) is the authoritative check; any contract it holds
  under "Feral File" that is not in the platform 53 and not in the 8 above gets the same
  audit. Independently, ask Ryan for the contract address + chain per collection — his 57
  are keyed on collection ownership on OpenSea's side and may include non-mainnet chains.
- **(b) collection_uuid pinning** for this class: per-token uuid5 of `collection_name` →
  needs one stored value per collection, server-side (no series rows). Design pending;
  see `ops/opensea-metadata-path/README.md` § special-project class.
- Census blind spot: file an agentic-workflows issue so token-health-monitor can take a
  contract list in addition to the exhibition walk.
