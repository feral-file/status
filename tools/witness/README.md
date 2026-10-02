# witness

A **witness entry** is one dated, signed statement about what the public
readers say an address holds, and what the chain itself says, at one block.
It is the smallest unit of a public log of who-holds-what: one address, two
or more readers, their set differences, and a chain check on a sample and on
every disagreement. Entries are published on their own site, <https://witness.feralfile.com>,
built by `build_witness.py` in this repository. There is no log service; a
second party produces an entry with this tool (or their own, in the same
shape) and signs it with their own key.

```bash
python3 tools/witness/witness.py --address 0x830cc132dd66F6491cEAA20206f398247143d9CF
python3 tools/witness/witness.py --address tz1gMfctX4hBNpkUoE7RcYPBhNc1hpHddqh4
node tools/witness/sign.mjs data/witness/holdings_<…>.json --key-file ~/.config/witness.key
node tools/witness/verify.mjs data/witness/holdings_<…>.json
```

`--name thefunnyguys.tez` resolves a name forward (ENS through Blockscout,
Tezos Domains through TzKT), refuses if it does not resolve to `--address`,
and records it; without it the entry carries the reverse record, if any.

`witness.py` is stdlib Python (>= 3.11); `sign.mjs` and `verify.mjs` are
zero-dependency Node (>= 18). The signer key is a 32-byte Ed25519 seed (hex),
PKCS#8 DER (base64), or PEM. `--ff-cli-config` signs with the key
[ff-cli](https://github.com/feral-file/ff-cli) uses for playlists, so the
same identity appears on both.

## What one run does

1. **Readers.** Ask each reader for the address's holdings. Ethereum: the
   Feral File indexer (`indexer-v2.feralfile.com/graphql`, `tokens(owners:)`,
   with unviewable and moderated tokens included so the list is the whole
   list) and Blockscout's public API (`/addresses/{address}/nft`, ERC-721 and
   ERC-1155). Tezos: TzKT (`/tokens/balances?account=&balance.gt=0`) and
   objkt's GraphQL (`token_holder`, FA2 only). All keyless. Each reader's full
   list is written to the `.lists.json` sibling and referenced from the entry
   by SHA-256. The chain is chosen from the address prefix.
2. **Pin a block.** The head block on the primary node after the reader
   fetches. Every chain read below is at that block (Tezos: by block hash).
3. **Compare.** Per standard, keyed `contract:token_id`: in both, only in A,
   only in B.
4. **Chain check.** Ethereum: `eth_call` at the pinned block, `ownerOf(tokenId)`
   equals the address for ERC-721, `balanceOf(address, tokenId) > 0` for
   ERC-1155; a revert counts as not held. Tezos: the contract's `%ledger` big
   map, located by walking the contract's own storage type from the node,
   read by key hash (`blake2b` of the packed key): key `(address, token_id)`
   to balance, or key `token_id` to owner; a missing key is not held. Run on a
   seeded random sample of `--sample` tokens from each reader's list (seed
   defaults to the block number, so the sample is reproducible), and on every
   token the readers disagree about. A contract that cannot be asked this way
   (no such selector; no `%ledger`; an unsupported ledger layout; FA1.2) is
   recorded as unanswerable, and a provider error after retries as no reply;
   neither counts for or against a reader.
5. **Second node.** Every "not held" verdict is re-read on a second RPC
   provider; any disagreement between providers is recorded under
   `rpc_recheck`.

## Entry schema (`feral-file/witness-holdings/0.1`)

| Field | Meaning |
| :-- | :-- |
| `schema`, `kind` | `feral-file/witness-holdings/0.1`, `holdings`. |
| `subject` | `chain` (CAIP-2: `eip155:1`, `tezos:NetXdQprcVkpaWU`), `address`, `name` with `name_system` (`ens` or `tezos-domains`) and `name_source`; Ethereum entries also carry `ens` for the first entry's readers. |
| `observed_at` | When the entry was assembled (UTC). |
| `chain_state` | `block` (number or level), `block_hash`, `block_timestamp`, primary `rpc`. Every chain verdict is at this block. |
| `readers[]` | One per reader: `name`, `operator`, `endpoint`, `query`, `fetched_at`, `count` (`total`, `erc721`, `erc1155`), `list_sha256` (over the sorted `contract:token_id:standard` lines), `notes`. |
| `comparison.pairs[]` | Per standard: `both`, `only_<reader>` counts. |
| `chain_check.samples[]` | Per reader: `seed`, `checked`, `held`, `not_held`, `of_which_reverted`, `unanswerable` (the contract faults on the call, e.g. CryptoPunks has no `ownerOf`), `no_reply` (the RPC gave no chain answer after retries), and `tokens[]` with the chain's answer per token. |
| `chain_check.differences[]` | Per standard and direction (`listed_by`, `missing_from`): the same tally and `tokens[]`, covering every disagreement, not a sample. |
| `chain_check.rpc_recheck` | Second-provider re-read of every not-held verdict: `confirmed`, `secondary_unanswered` (the second provider gave no chain answer; not a disagreement), and `rpc_disagreements` (empty when the two providers agree on every answered read). |
| `lists` | The sibling file with both readers' full lists, and its SHA-256. |
| `produced_by` | Tool path, repo, this document. |
| `signatures[]` | DP-1 v1.1.0 envelopes: `alg` (`ed25519`), `kid` (did:key of the signer), `ts`, `payload_hash`, `role` (`witness`), `sig` (base64url). Appending a signature does not change the payload hash. |

Reading an entry: a token the reader lists that the chain says is held
elsewhere (or whose `ownerOf` reverts) is a reader error or lag; a token the
chain says the address holds that a reader omits is an under-count. A
`held: false` row in a sample is the alert; `differences[]` says which reader
is right about each disputed token.

## Signing and verifying

The signed bytes are the entry without `signature`/`signatures`, serialized
with keys sorted recursively and no whitespace (JSON Canonicalization Scheme
for the values this tool emits: strings, integers, booleans, null, arrays,
objects), followed by one `\n`. `payload_hash` is `sha256:` plus the hex
SHA-256 of those bytes. `sig` is the Ed25519 signature over that 32-byte
digest, base64url. `kid` is `did:key:z` plus base58btc of `0xed01` plus the
32-byte public key. This is exactly the envelope `dp1-js` produces for
playlists (`SignMultiEd25519`) and verifies (`VerifyMultiSignaturesJSON`), so
either verifier accepts it. `verify.mjs` needs nothing installed.

## Appending a second entry

Run the same check from your own vantage point: your own reader(s), your own
RPC, your own key. Keep the schema; add your reader under `readers[]` with its
`operator`. Publish the file wherever you publish things and send the URL. If
you would rather it sit next to ours, open a PR adding it under
`data/witness/`; the build lists every entry it finds there. The word
"commons" waits until an entry exists that Feral File did not write.
