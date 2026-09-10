# Runbook — crystalline `setTokenBaseURI` (one owner tx)

*2026-09-04 · Requested by Brandon · Part of the CDN-retirement phase-2 rollout
(feral-file/feral-file#3435). You are receiving this because you hold the key
for the contract owner address below.*

## What this is

The crystalline exhibition contract (`FeralfileExhibitionV4_2`) builds
`tokenURI` as `<baseURI><tokenId>`. Its base URI currently points at an IPFS
metadata directory whose docs reference the retiring CDN. A rewritten
directory (same docs byte-for-byte, only media URLs changed to `ipfs://`,
9,048/9,048 independently verified) is already pinned on our IPFS cluster.

The fix is **ONE transaction**: `setTokenBaseURI("ipfs://<newDir>/")`.
The function is `onlyOwner`, so it must be sent from the owner address —
the key you hold.

| | |
|---|---|
| Chain | Ethereum mainnet (chainId 1) |
| Contract | `0xBE0A4E26a156B2a60cF515E86b3Df9756DEE1952` |
| Sender (owner) | `0x1d05cf6c6beb0c869851bfdb9510d4e44e855ad6` |
| Old base URI | `ipfs://QmY67Gq1514Zj1yWtHxoHeoVj8FpFLM5ZNSNQejjirxKTo/` |
| New base URI | `ipfs://QmNP6RC7Z5DRV8sQsmRgssQS3GP77BUCAK2UV4q94WfiMv/` |
| Gas | ~50k gas, capped at 1 gwei (the tool waits for cheap gas) — cost is negligible, but the owner address needs a small ETH balance |

## Hard rules

1. **Do NOT trigger an OpenSea metadata refresh** for this contract afterwards.
   Refresh is gated on an open OpenSea incident
   (`ops/opensea-metadata-path-incident.md`) — Brandon handles that separately.
2. Only sign the exact payload the tool produces. The `broadcast` step
   re-verifies the signed bytes (chainId / to / value / calldata / sender)
   and refuses anything that differs.
3. A signed tx is nonce-bound — broadcast promptly after signing, and don't
   send any other tx from the owner address in between.
4. The tool aborts unless the on-chain state matches the table above
   (owner, current base URI, sample tokens served by the new dir). If any
   check fails, stop and ping Brandon — don't work around it.

## Prerequisites

- A checkout of the `status` repo; everything runs from
  `tools/update-token-uri/` (Node 18+; `npm install` there if `node_modules`
  is missing — the only dependency is ethers).
- Any Ethereum mainnet `RPC_URL` (read + relay only; e.g. an Infura endpoint —
  some office/home networks DNS-block the free public RPCs).
- The owner key. It never touches disk in this flow (env var, or the vault
  if that's where it lives — both paths below).

## Steps

### 1 · Config

```bash
cd tools/update-token-uri
cp v4-base-uri.config.example.json v4-base-uri.config.json
```

Edit two fields in `v4-base-uri.config.json` (everything else is prefilled
and must not change):

- `senderAddress`: `0x1d05cf6c6beb0c869851bfdb9510d4e44e855ad6`
- `senderAccount`: your vault account id if the key is vault-held;
  otherwise any label, e.g. `"self-held"` (only echoed into the sign
  request — unused when you sign locally).

### 2 · Preflight (read-only)

```bash
RPC_URL=… node v4-base-uri.mjs preflight
```

Verifies you-are-owner, on-chain base URI = old dir, and that the new dir
actually serves clean sample docs through our gateway. All ✓ or stop.

### 3 · Build the tx

```bash
RPC_URL=… node v4-base-uri.mjs tx > txreq-base.json
```

Dry-runs the call, picks nonce + EIP-1559 fees (waits until total fee
≤ 1 gwei), and writes the sign request to `txreq-base.json`.

### 4 · Sign — pick ONE path

**A. Key is in the Feral File vault** under your account:

```bash
curl -sS -X POST "$VAULT_URL/sign" -H "Content-Type: application/json" \
  -H "X-API-KEY: $VAULT_API_KEY" -d @txreq-base.json | tee signed-tx.json
```

**B. You hold the raw key yourself** — save this as `sign-local.mjs` next to
the tool and run it with the key in an env var (never write the key to disk):

```js
// sign-local.mjs — sign txreq-base.json with a locally held key
import { ethers } from 'ethers';
import fs from 'node:fs';
const OWNER = '0x1d05cf6c6beb0c869851bfdb9510d4e44e855ad6';
const req = JSON.parse(fs.readFileSync(process.argv[2] ?? 'txreq-base.json', 'utf8')).payload;
const w = new ethers.Wallet(process.env.OWNER_KEY ?? (() => { throw new Error('OWNER_KEY env required'); })());
if (w.address.toLowerCase() !== OWNER) { console.error(`key is for ${w.address}, not the owner — aborting`); process.exit(1); }
const signed = await w.signTransaction({
  chainId: req.chain_id, nonce: req.nonce, to: req.to, value: 0, data: req.data,
  gasLimit: req.gas_limit, maxFeePerGas: req.max_fee_per_gas,
  maxPriorityFeePerGas: req.max_priority_fee_per_gas, type: 2,
});
fs.writeFileSync('signed-tx.json', JSON.stringify({ signed_tx: signed }));
console.error('wrote signed-tx.json for', w.address);
```

```bash
OWNER_KEY=0x… node sign-local.mjs txreq-base.json
```

(If the key lives in a hardware wallet instead, stop here and tell Brandon —
we'll arrange a different signing path rather than extracting the key.)

### 5 · Broadcast

```bash
RPC_URL=… node v4-base-uri.mjs broadcast signed-tx.json
```

Re-verifies the signed bytes, dry-runs once more, relays, waits for
2 confirmations, then re-reads `tokenURI` on-chain and confirms it now
starts with the new dir. The last lines should be:

```
tx sent: 0x…
✓ mined in block …
✓ post-check: tokenURI(…) = ipfs://QmNP6RC7…/…
```

### 6 · Report back

Send Brandon the tx hash and the broadcast output. That's everything —
the follow-up DB alignment runs on our side, and OpenSea stays untouched
per hard rule 1. Afterwards `rm txreq-base.json signed-tx.json` and unset
`OWNER_KEY` from your shell.
