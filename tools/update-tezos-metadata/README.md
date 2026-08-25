# Repoint Tezos FA2 token metadata (`update_edition_metadata`)

Ops tool for fixing broken token metadata on a Tezos `FeralfileExhibitionV2`
FA2 contract. Each token's `token_info` holds a single key `""` →
`bytes("ipfs://<cid>")` pointing at a TZIP-21 JSON, so a bad `artifactUri`
is fixed by pinning a replacement JSON and re-pointing the token through the
trustee-only `update_edition_metadata` entrypoint (`FF_NOT_TRUSTEE` otherwise).
The entrypoint takes a **list**, so tokens are updated in batches.

**First use:** feral-file/feral-file#3435 — *FeralVerse*
(`KT1JCd3QHFgNZRatQuniDi8evTtyuhKFb3DC`), 142 tokens in two series whose
`artifactUri` pointed at an unplayable HLS master playlist. Replacement JSONs
were generated in `../../ops/3435-hls-fix/feralverse-metadata-fix/` and pinned on prod-02 by its
`pin.sh`. Precedent for the entrypoint: trustee `tz1Q4DxSJ2…` batches on
2023-05-17 (visible on tzkt).

Sibling tool for the Ethereum side: `../update-token-uri/`. Same model as
`feral-file-server/scripts/withdraw-v4-tokens`: manual, human-in-the-loop,
**no key ever leaves the vault**.

---

## How it works

Taquito does counter / estimation / forging / preapply / injection. The only
thing it cannot do is sign, and for that `VaultSigner`:

1. **Parses the forged bytes** it is handed (`@taquito/local-forging`) and
   refuses to sign unless the operation is exactly the batch we built: one
   transaction, from the trustee, to `contract`, amount 0, entrypoint
   `update_edition_metadata`, the expected token ids, each `token_info` =
   `{ "": bytes("ipfs://<new cid>") }`.
2. Posts `0x03 || forged` to autonomy-vault (`scheme: tezos-operation`,
   `payload.forged_op_bytes`). The vault asserts the `0x03` watermark,
   blake2b-256-hashes, and Ed25519-signs with the account's derived Tezos key
   (`services/autonomy-vault/sign.go signTezosOperation`).
3. Verifies the response: `message_hash` must equal a local blake2b-256 of the
   same bytes, `public_key` must equal the trustee's on-chain `manager_key`;
   converts the generic `sig…` to `edsig…` and returns the signed bytes.

Before any of that, `run` calls the vault's `GET /accounts/:account_number`
and requires `tezos_address` = `senderAddress` and `tezos_public_key` = the
chain's `manager_key`, so the account identifier cannot be pointing at a
different key.

`preflight` reads every token's current `token_info` (must equal the csv's
old CID — else the csv is stale), fetches every **new** JSON through the
gateway `token_info` will point at (`ipfs.feralfile.com`, `Gateway.NoFetch`,
so a 404 means "not pinned on prod-02"), requires `artifactUri` to be `ipfs://`
and `formats[0]` to be `video/mp4` for the same URI, then simulates a full
batch as the trustee (`run_operation`; no signature needed).

Every batch is post-checked against fresh storage before the next one is
signed; `progress.json` records the op hash per token, so a rerun skips what
already landed.

### Where the DB stands

Wallets, marketplaces (objkt) and the indexer read `token_info` from chain.
The Feral File DB mirror has its own copy of the media URLs and does **not**
follow chain updates — it needs a separate DB update (Hieu /
feral-file-server), after which the daily token-health sweep and the
status-page census pick the change up.

---

## Safety rules

1. **One batch in flight at a time.** `run` signs a batch, injects, waits for
   2 confirmations, post-checks, then continues. Never run two copies.
2. **Always preflight the same day you run** — it exits non-zero if any row
   is blocked.
3. **Trial with `--limit 1`** (one token, one op), verify on tzkt and through
   the gateway, then run the rest.
4. The trustee is also used by the server for Tezos mints/transfers. Check
   nothing is in flight from it before running (tzkt: pending ops for the
   address; server DB `tezos_tx` or equivalent).
5. Never commit `config.json`, `progress.json`, `forged-*` (`.gitignore`).

---

## Setup

```bash
cd tools/update-tezos-metadata
npm install                         # @taquito/*, @stablelib/blake2b
cp config.example.json config.json  # fill in senderAccount
```

| Field | Value |
|---|---|
| `rpcUrl` | a mainnet RPC (`https://rpc.tzkt.io/mainnet` works from most networks) |
| `contract` | the FA2 exhibition contract |
| `senderAddress` | a listed trustee (`storage.trustee.trustees`). FeralVerse: `tz1fcVFFVujFmnDsWEV1nhGukJTkgXtDKZmm` (the vault-held one; `tz1Q4DxSJ2…` is the other) |
| `senderAccount` | the vault account identifier whose derived Tezos key is that trustee |
| `metadataGateway` | `https://ipfs.feralfile.com/ipfs/` |
| `updates` | csv `token_id,old_metadata_cid,new_metadata_cid` (output of `feralverse-metadata-fix/pin.sh`) |
| `batchSize` | tokens per operation (20 → ~1 kmutez fee/op; 142 tokens = 8 ops) |

Env: `VAULT_URL`, `VAULT_API_KEY` (the feralfile `X-API-KEY`, not the admin
key) — `run` only.

---

## Workflow

```bash
# 0 · the replacement JSONs must already be pinned on prod-02
#     (../../ops/3435-hls-fix/feralverse-metadata-fix/pin.sh → result.csv)

# 1 · preflight — every row TODO, none BLOCKED, simulation ✓
node update-tezos-metadata.mjs preflight

# 2 · trial: one token
VAULT_URL=… VAULT_API_KEY=… node update-tezos-metadata.mjs run --limit 1
#     → tzkt: op applied, token_metadata row now bytes("ipfs://<newCid>")
#     → curl https://ipfs.feralfile.com/ipfs/<newCid> | jq .artifactUri

# 3 · the rest (batches of batchSize)
VAULT_URL=… VAULT_API_KEY=… node update-tezos-metadata.mjs run

# 4 · verify
node update-tezos-metadata.mjs check      # expect N/N UPDATED ✓
```

---

## After the chain is updated

- DB update for the same tokens (Hieu).
- Old metadata JSONs can be unpinned from prod-02 once nothing references
  them — not before.
- Re-run the token-health census and rebuild status.feralfile.com.
