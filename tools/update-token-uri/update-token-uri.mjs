// update-token-uri.mjs — repoint FeralfileExhibitionV2 token metadata at
// replacement IPFS metadata directories via updateArtworkEditionIPFSCid.
//
// Background (feral-file/feral-file#3435): V2 tokenURI() is
//   _tokenBaseURI + artworkEditions[tokenId].ipfsCID + "/metadata.json"
// so fixing a broken animation_url means pinning a new metadata directory and
// registering its CID on-chain, one transaction per token. The function is
// `onlyAuthorized` (trustee or owner); the trustee key lives in autonomy-vault.
//
// NO LOCAL KEYS: every transaction is signed inside the vault (scheme `eth-tx`),
// mirroring feral-file-server/scripts/withdraw-v4-tokens. Locally this script
// only reads chain state, builds requests, verifies the vault's signed_tx
// byte-for-byte (chainId / to / value / calldata / sender), dry-runs, relays.
//
// Commands (see README.md for the runbook):
//   node update-token-uri.mjs preflight                    → on-chain + gateway checks for every row; prints a TODO list
//   node update-token-uri.mjs tx        <edition>          → dry-run, then vault eth-tx sign request (stdout)
//   node update-token-uri.mjs broadcast <edition> <vault-tx.json> → verify signed_tx, dry-run, relay, wait 2 confs
//   node update-token-uri.mjs check                        → tokenURI()/ipfsCID per row vs expected
//   node update-token-uri.mjs base-uri-tx                  → setTokenBaseURI(config.tokenBaseURI): dry-run, vault eth-tx sign request (stdout)
//   node update-token-uri.mjs base-uri-broadcast <vault-tx.json> → verify signed_tx, dry-run, relay, re-read tokenURI
//
// Config: ./config.json next to this script, or $UPDATE_CONFIG.
// Env:    RPC_URL (read + relay only, no keys).

import { ethers } from 'ethers';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const configPath = process.env.UPDATE_CONFIG ?? path.join(scriptDir, 'config.json');

function fail(msg) { console.error('✗', msg); process.exit(1); }
function ok(msg)   { console.error('✓', msg); } // stderr keeps stdout pure JSON for `tx`

if (!fs.existsSync(configPath)) fail(`config not found: ${configPath} — copy config.example.json to config.json`);
const cfg = JSON.parse(fs.readFileSync(configPath, 'utf8'));

const CHAIN_ID = cfg.chainId ?? 1;
const CONTRACT = cfg.contract;
const SENDER = cfg.senderAddress;      // trustee (or owner) address — tx sender / gas payer
const SENDER_ACCOUNT = cfg.senderAccount; // vault account identifier for that key
const GATEWAY = (cfg.metadataGateway ?? 'https://ipfs.bitmark.com/ipfs/').replace(/\/?$/, '/');
const NEW_BASE = cfg.tokenBaseURI; // optional: target for setTokenBaseURI (e.g. https://ipfs.feralfile.com/ipfs/)
if (NEW_BASE !== undefined && !/^https:\/\/[a-z0-9.-]+\/ipfs\/$/.test(NEW_BASE))
  fail('config: tokenBaseURI must look like https://<gateway>/ipfs/ (trailing slash — the contract appends <cid>/metadata.json directly)');

if (!ethers.isAddress(CONTRACT ?? '')) fail('config: contract must be an address');
if (!ethers.isAddress(SENDER ?? '') || SENDER === ethers.ZeroAddress) fail('config: senderAddress must be the trustee/owner address');
if (!SENDER_ACCOUNT || SENDER_ACCOUNT.startsWith('FILL')) fail('config: senderAccount must be the vault account identifier');

// ---------------------------------------------------------------------------
// Updates: CSV with header edition,token_id,old_metadata_cid,new_metadata_cid
// (the output of rewilded-metadata-fix/pin.sh).

const updatesPath = path.resolve(scriptDir, cfg.updates ?? 'updates.csv');
if (!fs.existsSync(updatesPath)) fail(`updates csv not found: ${updatesPath}`);
const UPDATES = fs.readFileSync(updatesPath, 'utf8').trim().split('\n').slice(1).filter(Boolean).map((line) => {
  const [edition, tokenId, oldCid, newCid] = line.split(',').map((s) => s.trim());
  if (!/^\d+$/.test(edition)) fail(`bad edition in updates csv: ${line}`);
  if (!/^\d+$/.test(tokenId)) fail(`bad token_id in updates csv: ${line}`);
  if (!/^(Qm[1-9A-HJ-NP-Za-km-z]{44}|bafy[a-z2-7]{55,})$/.test(newCid)) fail(`bad new_metadata_cid in updates csv: ${line}`);
  return { edition, tokenId, oldCid, newCid };
});
if (UPDATES.length === 0) fail('updates csv has no rows');
if (new Set(UPDATES.map((u) => u.tokenId)).size !== UPDATES.length) fail('updates csv: duplicate token_id');
if (new Set(UPDATES.map((u) => u.newCid)).size !== UPDATES.length) fail('updates csv: duplicate new_metadata_cid — the contract rejects a CID registered twice');

const [cmd, arg1, txRespFile] = process.argv.slice(2);
const byEdition = (ed) => {
  const u = UPDATES.find((x) => x.edition === String(ed));
  if (!u) fail(`edition ${ed} not in ${path.basename(updatesPath)}`);
  return u;
};

// Paced provider (same reasoning as withdraw-v4.mjs): space every JSON-RPC
// request so public gateways don't rate-limit preflight bursts.
const RPC_GAP_MS = Number(process.env.RPC_MIN_GAP_MS ?? 300);
let rpcNextSlot = 0;
class PacedProvider extends ethers.JsonRpcProvider {
  async send(method, params) {
    if (RPC_GAP_MS > 0) {
      const now = Date.now();
      const slot = Math.max(now, rpcNextSlot);
      rpcNextSlot = slot + RPC_GAP_MS;
      if (slot > now) await new Promise((res) => setTimeout(res, slot - now));
    }
    return super.send(method, params);
  }
}
const rpc = () => new PacedProvider(process.env.RPC_URL ?? 'https://ethereum-rpc.publicnode.com', CHAIN_ID,
  { staticNetwork: true, batchMaxCount: 1 });

const ABI = [
  'function owner() view returns (address)',
  'function trustee() view returns (address)',
  'function ownerOf(uint256) view returns (address)',
  'function tokenURI(uint256) view returns (string)',
  'function artworkEditions(uint256) view returns (uint256 editionID, string ipfsCID)',
  'function updateArtworkEditionIPFSCid(uint256 tokenId, string ipfsCID)',
  'function setTokenBaseURI(string baseURI_)',
];
const iface = new ethers.Interface(ABI);
const calldataFor = (u) => iface.encodeFunctionData('updateArtworkEditionIPFSCid', [BigInt(u.tokenId), u.newCid]);
const baseUriCalldata = () => iface.encodeFunctionData('setTokenBaseURI', [NEW_BASE]);

// _tokenBaseURI has no getter on V2; derive it from tokenURI() of a known token.
async function currentBaseURI(c, u) {
  const [uri, { ipfsCID }] = await Promise.all([c.tokenURI(u.tokenId), c.artworkEditions(u.tokenId)]);
  const suffix = `${ipfsCID}/metadata.json`;
  if (!uri.endsWith(suffix)) fail(`tokenURI ${uri} does not end with ${suffix} — unexpected contract shape`);
  return uri.slice(0, -suffix.length);
}

// Shared "sign this calldata in the vault" request builder (eth-tx scheme).
async function vaultTxRequest(provider, data, label) {
  await provider.call({ from: SENDER, to: CONTRACT, data, value: 0 });
  ok(`eth_call dry-run passed: ${label}`);
  const nonce = await provider.getTransactionCount(SENDER, 'pending');
  const gas = await provider.estimateGas({ from: SENDER, to: CONTRACT, data });
  const gasLimit = gas * 120n / 100n;
  let fees;
  for (let attempt = 1; ; attempt++) {
    try { fees = await provider.getFeeData(); if (fees.maxFeePerGas && fees.maxPriorityFeePerGas) break; } catch { /* retry */ }
    if (attempt >= 5) fail('RPC returned no EIP-1559 fee data after 5 attempts');
    console.error(`· fee data unavailable (attempt ${attempt}) — retrying in ${3 * attempt}s`);
    await new Promise((res) => setTimeout(res, 3000 * attempt));
  }
  ok(`nonce=${nonce} gasEstimate=${gas} gasLimit=${gasLimit} maxFee=${ethers.formatUnits(fees.maxFeePerGas, 'gwei')} gwei tip=${ethers.formatUnits(fees.maxPriorityFeePerGas, 'gwei')} gwei`);
  return {
    account_number: SENDER_ACCOUNT,
    chain: 'ethereum',
    scheme: 'eth-tx',
    payload: {
      chain_id: CHAIN_ID, nonce, to: CONTRACT, value: '0x0', data,
      gas_limit: Number(gasLimit),
      max_fee_per_gas: '0x' + fees.maxFeePerGas.toString(16),
      max_priority_fee_per_gas: '0x' + fees.maxPriorityFeePerGas.toString(16),
      tx_type: 'eip1559',
    },
  };
}

// Shared verify-and-relay for a vault-signed tx. Hard-fails unless the vault
// signed exactly `expectedData` from SENDER to CONTRACT with zero value.
async function relaySigned(provider, txRespPath, expectedData, label) {
  const txResp = JSON.parse(fs.readFileSync(txRespPath, 'utf8'));
  if (!txResp.signed_tx) fail(`no 'signed_tx' in ${txRespPath}`);
  const tx = ethers.Transaction.from(txResp.signed_tx);
  if (tx.chainId !== BigInt(CHAIN_ID)) fail(`chainId ${tx.chainId} ≠ ${CHAIN_ID}. DO NOT RELAY.`);
  if (!tx.to || tx.to.toLowerCase() !== CONTRACT.toLowerCase()) fail(`to ${tx.to} ≠ exhibition contract. DO NOT RELAY.`);
  if (tx.value !== 0n) fail(`value ${tx.value} ≠ 0. DO NOT RELAY.`);
  if (tx.data.toLowerCase() !== expectedData.toLowerCase()) fail('calldata mismatch — the vault signed a different call. DO NOT RELAY.');
  if (!tx.from || tx.from.toLowerCase() !== SENDER.toLowerCase()) fail(`sender ${tx.from} ≠ ${SENDER}. DO NOT RELAY.`);
  ok(`vault-signed tx verified: from=${tx.from} nonce=${tx.nonce} ${label}`);
  await provider.call({ from: tx.from, to: tx.to, data: tx.data, value: 0 });
  ok('final eth_call dry-run passed');
  console.log('tx hash (pre-relay):', tx.hash);
  const sleep = (ms) => new Promise((res) => setTimeout(res, ms));
  let relayed = false;
  for (let attempt = 1; attempt <= 3 && !relayed; attempt++) {
    try { await provider.broadcastTransaction(txResp.signed_tx); relayed = true; }
    catch (e) {
      const msg = (e.error?.message ?? e.shortMessage ?? e.message ?? '').toLowerCase();
      if (msg.includes('already known') || msg.includes('known transaction') || msg.includes('nonce too low')) { relayed = true; break; }
      console.error(`· relay attempt ${attempt} errored (${msg}) — checking whether the tx landed anyway`);
      for (let i = 0; i < 4 && !relayed; i++) { await sleep(5000); try { if (await provider.getTransaction(tx.hash)) relayed = true; } catch { /* poll */ } }
      if (!relayed && attempt === 3) fail(`relay failed 3× and ${tx.hash} is not in the network — nonce still free; re-run broadcast to retry`);
    }
  }
  console.log('tx sent:', tx.hash);
  const rcpt = await provider.waitForTransaction(tx.hash, 2);
  if (!rcpt) fail(`no receipt for ${tx.hash} — check manually`);
  if (rcpt.status !== 1) fail(`tx ${tx.hash} REVERTED in block ${rcpt.blockNumber} — nothing changed`);
  ok(`mined in block ${rcpt.blockNumber}, status SUCCESS, gasUsed ${rcpt.gasUsed}`);
}

async function assertAuthorized(c) {
  const [owner, trustee] = await Promise.all([c.owner(), c.trustee()]);
  const s = SENDER.toLowerCase();
  if (s !== owner.toLowerCase() && s !== trustee.toLowerCase())
    fail(`senderAddress ${SENDER} is neither owner (${owner}) nor trustee (${trustee}) — updateArtworkEditionIPFSCid would revert`);
  ok(`sender ${SENDER} is authorized (${s === trustee.toLowerCase() ? 'trustee' : 'owner'})`);
}

// Fetch the replacement metadata through the gateway the tokenURI actually
// uses. That gateway is Gateway.NoFetch, so a 404 here means "not pinned on
// prod-02" — registering the CID on-chain would point wallets at nothing.
async function gatewayCheck(u) {
  const url = `${GATEWAY}${u.newCid}/metadata.json`;
  let res;
  try { res = await fetch(url, { signal: AbortSignal.timeout(60_000) }); }
  catch (e) { return { okay: false, why: `fetch failed: ${e.message}` }; }
  if (!res.ok) return { okay: false, why: `HTTP ${res.status}` };
  let m;
  try { m = await res.json(); } catch { return { okay: false, why: 'not JSON' }; }
  if (typeof m.animation_url !== 'string' || !m.animation_url.startsWith('ipfs://'))
    return { okay: false, why: `animation_url is ${JSON.stringify(m.animation_url)}` };
  if (String(m.edition_index) !== u.edition)
    return { okay: false, why: `edition_index ${m.edition_index} ≠ ${u.edition} — wrong metadata for this token` };
  return { okay: true, why: `animation_url=${m.animation_url.slice(0, 24)}… edition_index=${m.edition_index}` };
}

// ---------------------------------------------------------------------------

if (cmd === 'preflight') {
  const provider = rpc();
  const c = new ethers.Contract(CONTRACT, ABI, provider);
  await assertAuthorized(c);
  console.error(`tokenBaseURI: ${await currentBaseURI(c, UPDATES[0])}${NEW_BASE ? ` → config.tokenBaseURI ${NEW_BASE}` : ''}`);
  let todo = 0, done = 0, blocked = 0;
  for (const u of UPDATES) {
    const [{ ipfsCID }, uri] = await Promise.all([c.artworkEditions(u.tokenId), c.tokenURI(u.tokenId)]);
    if (ipfsCID === u.newCid) { done++; console.log(`ed ${u.edition.padStart(3)}  DONE     on-chain already ${u.newCid}`); continue; }
    if (ipfsCID !== u.oldCid) { blocked++; console.log(`ed ${u.edition.padStart(3)}  BLOCKED  on-chain ipfsCID ${ipfsCID} ≠ csv old ${u.oldCid} — csv is stale, regenerate`); continue; }
    if (!uri.includes(ipfsCID)) { blocked++; console.log(`ed ${u.edition.padStart(3)}  BLOCKED  tokenURI ${uri} does not embed ipfsCID — unexpected contract shape`); continue; }
    const gw = await gatewayCheck(u);
    if (!gw.okay) { blocked++; console.log(`ed ${u.edition.padStart(3)}  BLOCKED  new metadata not servable: ${gw.why} (${GATEWAY}${u.newCid}/metadata.json)`); continue; }
    // Dry-run the exact call as the sender — catches "ipfs id has registered" etc.
    try {
      await provider.call({ from: SENDER, to: CONTRACT, data: calldataFor(u), value: 0 });
    } catch (e) {
      blocked++; console.log(`ed ${u.edition.padStart(3)}  BLOCKED  dry-run reverted: ${e.reason ?? e.shortMessage ?? e.message}`); continue;
    }
    todo++; console.log(`ed ${u.edition.padStart(3)}  TODO     ${ipfsCID} → ${u.newCid}  (${gw.why})`);
  }
  console.error(`\n${todo} to do · ${done} already done · ${blocked} blocked`);
  if (blocked) process.exit(2);

} else if (cmd === 'tx') {
  const u = byEdition(arg1);
  const provider = rpc();
  const c = new ethers.Contract(CONTRACT, ABI, provider);
  await assertAuthorized(c);
  const { ipfsCID } = await c.artworkEditions(u.tokenId);
  if (ipfsCID === u.newCid) fail(`edition ${u.edition}: on-chain ipfsCID is already ${u.newCid} — nothing to do`);
  if (ipfsCID !== u.oldCid) fail(`edition ${u.edition}: on-chain ipfsCID ${ipfsCID} ≠ csv old ${u.oldCid} — csv is stale`);
  const gw = await gatewayCheck(u);
  if (!gw.okay) fail(`edition ${u.edition}: new metadata not servable from ${GATEWAY}: ${gw.why}`);
  const req = await vaultTxRequest(provider, calldataFor(u), `updateArtworkEditionIPFSCid(…${u.tokenId.slice(-6)}, ${u.newCid})`);
  console.log(JSON.stringify(req, null, 2));

} else if (cmd === 'broadcast') {
  if (!txRespFile) fail('usage: broadcast <edition> <vault-tx.json>');
  const u = byEdition(arg1);
  const provider = rpc();
  await relaySigned(provider, txRespFile, calldataFor(u), `edition=${u.edition} newCid=${u.newCid}`);
  const c = new ethers.Contract(CONTRACT, ABI, provider);
  const { ipfsCID } = await c.artworkEditions(u.tokenId);
  if (ipfsCID !== u.newCid) fail(`post-check: on-chain ipfsCID is ${ipfsCID}, expected ${u.newCid}`);
  ok(`post-check: tokenURI now ${await c.tokenURI(u.tokenId)}`);

} else if (cmd === 'base-uri-tx') {
  if (!NEW_BASE) fail('config: tokenBaseURI is not set');
  const provider = rpc();
  const c = new ethers.Contract(CONTRACT, ABI, provider);
  await assertAuthorized(c);
  const cur = await currentBaseURI(c, UPDATES[0]);
  if (cur === NEW_BASE) fail(`tokenBaseURI is already ${cur} — nothing to do`);
  // The new gateway must serve the same metadata the current one does, for a
  // token we are NOT touching in this run as well as one we are.
  const probe = `${NEW_BASE}${(await c.artworkEditions(UPDATES[0].tokenId)).ipfsCID}/metadata.json`;
  const res = await fetch(probe, { signal: AbortSignal.timeout(60_000) }).catch((e) => ({ ok: false, status: e.message }));
  if (!res.ok) fail(`new gateway does not serve current metadata: HTTP ${res.status} for ${probe} — pin/verify before switching`);
  ok(`new gateway serves current metadata (${probe})`);
  const req = await vaultTxRequest(provider, baseUriCalldata(), `setTokenBaseURI(${cur} → ${NEW_BASE})`);
  console.log(JSON.stringify(req, null, 2));

} else if (cmd === 'base-uri-broadcast') {
  if (!NEW_BASE) fail('config: tokenBaseURI is not set');
  if (!arg1) fail('usage: base-uri-broadcast <vault-tx.json>');
  const provider = rpc();
  await relaySigned(provider, arg1, baseUriCalldata(), `setTokenBaseURI(${NEW_BASE})`);
  const c = new ethers.Contract(CONTRACT, ABI, provider);
  const cur = await currentBaseURI(c, UPDATES[0]);
  if (cur !== NEW_BASE) fail(`post-check: tokenBaseURI is ${cur}, expected ${NEW_BASE}`);
  ok(`post-check: tokenURI(…${UPDATES[0].tokenId.slice(-6)}) = ${await c.tokenURI(UPDATES[0].tokenId)}`);

} else if (cmd === 'check') {
  const c = new ethers.Contract(CONTRACT, ABI, rpc());
  const cur = await currentBaseURI(c, UPDATES[0]);
  console.log(`tokenBaseURI: ${cur}${NEW_BASE ? (cur === NEW_BASE ? '  (= config.tokenBaseURI ✓)' : `  (config.tokenBaseURI is ${NEW_BASE})`) : ''}`);
  let good = 0;
  for (const u of UPDATES) {
    const { ipfsCID } = await c.artworkEditions(u.tokenId);
    const mark = ipfsCID === u.newCid ? 'UPDATED ✓' : ipfsCID === u.oldCid ? 'old' : 'OTHER ⚠';
    if (ipfsCID === u.newCid) good++;
    console.log(`ed ${u.edition.padStart(3)}  …${u.tokenId.slice(-6)}  ${ipfsCID}  ${mark}`);
  }
  console.error(`${good}/${UPDATES.length} updated`);

} else {
  fail('usage: update-token-uri.mjs preflight | tx <edition> | broadcast <edition> <vault-tx.json> | check | base-uri-tx | base-uri-broadcast <vault-tx.json>');
}
