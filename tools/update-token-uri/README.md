# Repoint V2 token metadata (`updateArtworkEditionIPFSCid`)

Ops tool for fixing broken `tokenURI` metadata on a `FeralfileExhibitionV2`
exhibition contract. V2 builds `tokenURI(tokenId)` as

```
_tokenBaseURI + artworkEditions[tokenId].ipfsCID + "/metadata.json"
```

so a bad `animation_url` baked into a token's IPFS metadata directory can only
be fixed by pinning a replacement directory and registering its CID on-chain —
one `updateArtworkEditionIPFSCid(tokenId, newCid)` transaction per token,
callable by the contract's **trustee or owner**.

**First use:** feral-file/feral-file#3435 — *Rewilded Topography #1* (On Screen
Presence, `0xaDB387798599f5777CD0531c2ECb36007C1D1a51`), 50 editions whose
`animation_url` pointed at an unplayable HLS master playlist (42) or a CDN
pre-performance teaser (8). Replacement directories were generated in
`../../ops/3435-hls-fix/rewilded-metadata-fix/` and pinned on prod-02 by its `pin.sh`.

This is a **manual, human-in-the-loop** tool modelled on
`feral-file-server/scripts/withdraw-v4-tokens`. No key ever leaves the vault.

---

## How it works

1. `preflight` reads every row's on-chain `ipfsCID`, requires it to equal the
   csv's `old_metadata_cid` (else the csv is stale), fetches the **new**
   `metadata.json` through the gateway `tokenURI` actually uses
   (`ipfs.bitmark.com`, which is `Gateway.NoFetch` — a 404 means "not pinned on
   prod-02"), checks `edition_index` matches, and `eth_call`-dry-runs the exact
   update as the sender.
2. `tx <edition>` repeats those checks for one token, picks nonce + EIP-1559
   fees, and prints a vault `eth-tx` sign request.
3. The vault signs; `broadcast` decodes `signed_tx` and hard-fails unless
   chainId / to / value / calldata / sender all match, dry-runs again, relays,
   waits 2 confirmations, and re-reads `artworkEditions(tokenId)`.
4. `run-all.mjs` chains 2–3 for every row, strictly sequential, resumable.
5. `base-uri-tx` / `base-uri-broadcast` change the contract-wide prefix via
   `setTokenBaseURI` (one tx for the whole contract). Before signing it fetches
   a current token's `metadata.json` through the **new** gateway — the switch
   is refused if the new gateway can't serve what the old one serves.

### Why one tx per token

V2 has no batch setter. Gas is ~50–60k per call; 50 tokens ≈ 3M gas total.

### The uniqueness trap

`updateArtworkEditionIPFSCid` reverts with `ipfs id has registered` if the new
CID is already registered to any token in the contract. Every token therefore
needs its **own** metadata directory (they differ by `edition_index`/`name`, so
the CIDs are naturally distinct). The tool refuses a csv with duplicate
`new_metadata_cid`.

### Where the DB stands

`tokenURI` is what wallets, marketplaces and the indexer read. The Feral File
DB mirror (`feralfile.com/api/contracts/<addr>/tokens/<id>`) has its own
`animation_url` and does **not** follow on-chain updates automatically — it
needs a separate DB update (Hieu / feral-file-server), after which the daily
token-health sweep and the status-page census pick the change up.

---

## Safety rules

1. **A vault-signed tx is nonce-bound.** Broadcast promptly; never run while
   the server has an in-flight tx from the same sender (quiet-window check
   below). `run-all.mjs` signs one, relays it, waits for 2 confirmations, then
   moves on — it never holds two signed txs.
2. **Always preflight the same day you broadcast.** It exits non-zero if any
   row is blocked.
3. **Always do a 1-token trial first** (`--limit 1`), verify `tokenURI()` on
   Etherscan and the metadata through `ipfs.bitmark.com`, then run the rest.
4. Never commit `config.json`, `txreq-*`, `vault-tx-*`, `progress.json`
   (`.gitignore` covers them).

---

## Setup

```bash
cd tools/update-token-uri
npm install                         # ethers v6
cp config.example.json config.json  # fill in senderAccount
```

| Field | Value |
|---|---|
| `chainId` | `1` |
| `contract` | the V2 exhibition contract |
| `senderAddress` | the trustee (read it: `trustee()`) or owner address. Rewilded: trustee `0xbeb9f810862c40a144925f568b1853d72acc492f` |
| `senderAccount` | the vault account identifier holding that key |
| `metadataGateway` | `https://ipfs.bitmark.com/ipfs/` (what `_tokenBaseURI` is set to) |
| `updates` | path to the csv: `edition,token_id,old_metadata_cid,new_metadata_cid` (output of `rewilded-metadata-fix/pin.sh`) |
| `tokenBaseURI` | optional — target for `base-uri-tx`, e.g. `https://ipfs.feralfile.com/ipfs/` (trailing slash; the contract appends `<cid>/metadata.json`) |

Env: `RPC_URL` (any mainnet RPC; read + relay only), `VAULT_URL` /
`VAULT_API_KEY` (the feralfile `X-API-KEY`, not the vault admin key).

---

## Workflow

```bash
# 0 · the replacement metadata must already be pinned on prod-02
#     (../../ops/3435-hls-fix/rewilded-metadata-fix/pin.sh → result.csv)

# 1 · preflight — every row TODO, none BLOCKED
node update-token-uri.mjs preflight

# 2 · quiet-window check (server DB) — expect 0 rows
#     SELECT id, nonce, status FROM eth_tx
#     WHERE lower(address) = lower('<senderAddress>') AND status IN ('allocated','broadcast');

# 3 · trial: one token
VAULT_URL=… VAULT_API_KEY=… RPC_URL=… node run-all.mjs --limit 1
#     → Etherscan: UpdateArtworkEditionIPFSCid tx succeeded; tokenURI(tokenId) now ends in <newCid>/metadata.json
#     → curl https://ipfs.bitmark.com/ipfs/<newCid>/metadata.json | jq .animation_url

# 4 · the rest
VAULT_URL=… VAULT_API_KEY=… RPC_URL=… node run-all.mjs

# 5 · verify
node update-token-uri.mjs check        # expect N/N UPDATED ✓

# 6 · (optional) move the whole contract's tokenURI prefix to ipfs.feralfile.com
node update-token-uri.mjs base-uri-tx > txreq-base.json
curl -sS -X POST "$VAULT_URL/sign" -H "Content-Type: application/json" -H "X-API-KEY: $VAULT_API_KEY" -d @txreq-base.json | tee vault-tx-base.json
node update-token-uri.mjs base-uri-broadcast vault-tx-base.json
node update-token-uri.mjs check        # first line: tokenBaseURI = config.tokenBaseURI ✓
```

`ipfs.bitmark.com` and `ipfs.feralfile.com` are the same prod-02 kubo behind
Caddy (ff-deploy), so the base-URI switch is a naming change, not a hosting
change — every pinned metadata directory is served identically by both. Do it
after the per-token updates so a single `check` verifies both.

**RPC note:** the trustee is the platform account (nonce in the 15,000s), so
the quiet-window check is not optional. Some home networks DNS-block public
RPC hosts (`publicnode.com`, `flashbots.net`) — if `tx` fails with a TLS
altname error naming `blocking.asus.hns.tm`, set `RPC_URL` to a reachable
endpoint (e.g. `https://1rpc.io/eth` with `RPC_MIN_GAP_MS=1500`).

Manual, per-token equivalent of what `run-all.mjs` does:

```bash
node update-token-uri.mjs tx 23 > txreq-23.json
curl -sS -X POST "$VAULT_URL/sign" -H "Content-Type: application/json" -H "X-API-KEY: $VAULT_API_KEY" -d @txreq-23.json | tee vault-tx-23.json
node update-token-uri.mjs broadcast 23 vault-tx-23.json
```

---

## After the chain is updated

- Ask for the DB `animation_url` (and `image`, for the 8 CDN editions) to be
  updated to the same `ipfs://` values.
- Old metadata directories can be unpinned from prod-02 once nothing references
  them (not before — the previous `tokenURI` should keep resolving until every
  consumer has re-indexed).
- Re-run the token-health census and rebuild status.feralfile.com.
