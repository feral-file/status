// v4-base-uri.mjs — switch a FeralfileExhibitionV4/V4_2 contract's tokenBaseURI
// to a new tokenId-named IPFS metadata directory, with ONE onlyOwner tx.
//
// Phase-2 step 3 (feral-file/feral-file#3435): V4 tokenURI = _baseURI() +
// tokenId (decimal). Both V4 contracts already point at an IPFS dir; fixing
// crystalline's CDN media = build the rewritten dir (v4-dir-regen.py +
// mfs-batch-add.py), pin it, then setTokenBaseURI("ipfs://<newDir>/").
//
// Same NO-LOCAL-KEYS vault flow as update-token-uri.mjs (scheme eth-tx):
// this script reads chain state, builds the sign request, verifies the
// vault's signed_tx byte-for-byte, dry-runs, relays.
//
// Commands:
//   node v4-base-uri.mjs preflight                → owner + sample-token checks
//   node v4-base-uri.mjs tx                       → dry-run + vault sign request (stdout)
//   node v4-base-uri.mjs broadcast <vault-tx.json>→ verify signed_tx, relay, post-check
//
// Config ($V4_CONFIG or ./v4-base-uri.config.json):
//   { "chainId": 1, "contract": "0x…", "senderAddress": "0x…(owner)",
//     "senderAccount": "vault-account", "oldBaseURI": "ipfs://<oldDir>/",
//     "newBaseURI": "ipfs://<newDir>/", "gateway": "https://ipfs.feralfile.com/ipfs/",
//     "sampleTokenIds": ["…", "…"], "maxGasPriceGwei": 1 }
// Env: RPC_URL, MAX_GAS_GWEI, GAS_POLL_SECONDS.

import { ethers } from 'ethers';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const configPath = process.env.V4_CONFIG ?? path.join(scriptDir, 'v4-base-uri.config.json');
function fail(msg) { console.error('✗', msg); process.exit(1); }
function ok(msg) { console.error('✓', msg); }
if (!fs.existsSync(configPath)) fail(`config not found: ${configPath}`);
const cfg = JSON.parse(fs.readFileSync(configPath, 'utf8'));

const CHAIN_ID = cfg.chainId ?? 1;
const CONTRACT = cfg.contract;
const SENDER = cfg.senderAddress;
const SENDER_ACCOUNT = cfg.senderAccount;
const OLD_BASE = cfg.oldBaseURI;
const NEW_BASE = cfg.newBaseURI;
const GATEWAY = (cfg.gateway ?? 'https://ipfs.feralfile.com/ipfs/').replace(/\/?$/, '/');
const SAMPLES = cfg.sampleTokenIds ?? [];
const MAX_GAS_GWEI = Number(process.env.MAX_GAS_GWEI ?? cfg.maxGasPriceGwei ?? 1);
const GAS_POLL_S = Number(process.env.GAS_POLL_SECONDS ?? 60);
const MAX_FEE_WEI = ethers.parseUnits(String(MAX_GAS_GWEI), 'gwei');

const IPFS_DIR = /^ipfs:\/\/(Qm[1-9A-HJ-NP-Za-km-z]{44}|baf[a-z0-9]{20,})\/$/;
if (!IPFS_DIR.test(NEW_BASE ?? '')) fail('config: newBaseURI must be ipfs://<dirCID>/ (trailing slash — the contract appends the decimal tokenId)');
if (!IPFS_DIR.test(OLD_BASE ?? '')) fail('config: oldBaseURI must be ipfs://<dirCID>/ (the current on-chain value, for the swap check)');
if (!ethers.isAddress(CONTRACT ?? '')) fail('config: contract must be an address');
if (!ethers.isAddress(SENDER ?? '')) fail('config: senderAddress must be the owner address');
if (!SENDER_ACCOUNT) fail('config: senderAccount required');
if (SAMPLES.length < 2) fail('config: sampleTokenIds needs >= 2 token ids');

const ABI = [
  'function owner() view returns (address)',
  'function tokenURI(uint256) view returns (string)',
  'function setTokenBaseURI(string baseURI_)',
];
const iface = new ethers.Interface(ABI);
const calldata = iface.encodeFunctionData('setTokenBaseURI', [NEW_BASE]);
const rpc = () => new ethers.JsonRpcProvider(process.env.RPC_URL ?? fail('RPC_URL required'), CHAIN_ID, { staticNetwork: true, batchMaxCount: 1 });
const gwUrl = (base, id) => `${GATEWAY}${base.slice('ipfs://'.length)}${id}`;

async function sampleChecks(c) {
  for (const id of SAMPLES) {
    const uri = await c.tokenURI(id);
    if (uri !== OLD_BASE + id) fail(`tokenURI(…${id.slice(-8)}) = ${uri} ≠ oldBaseURI+id — config stale or wrong contract`);
    // the NEW dir must serve this token's doc with clean media
    const res = await fetch(gwUrl(NEW_BASE, id), { signal: AbortSignal.timeout(60_000) }).catch((e) => ({ ok: false, status: e.message }));
    if (!res.ok) fail(`new dir does not serve token …${id.slice(-8)}: HTTP ${res.status} — pin/verify the new dir first`);
    const m = await res.json().catch(() => fail(`new dir doc for …${id.slice(-8)} is not JSON`));
    const isIpfs = (v) => typeof v === 'string' && v.startsWith('ipfs://');
    if (!isIpfs(m.image)) fail(`new doc …${id.slice(-8)}: image is ${JSON.stringify(m.image)?.slice(0, 60)} — not ipfs://`);
    if (m.animation_url !== undefined && !isIpfs(m.animation_url)) fail(`new doc …${id.slice(-8)}: animation_url not ipfs://`);
    ok(`sample …${id.slice(-8)}: on-chain matches oldBaseURI; new dir serves clean doc (${String(m.name).slice(0, 40)})`);
  }
}

async function vaultTxRequest(provider) {
  await provider.call({ from: SENDER, to: CONTRACT, data: calldata, value: 0 });
  ok('eth_call dry-run passed: setTokenBaseURI');
  const nonce = await provider.getTransactionCount(SENDER, 'pending');
  const gas = await provider.estimateGas({ from: SENDER, to: CONTRACT, data: calldata });
  const gasLimit = gas * 120n / 100n;
  let tip, baseFee;
  for (;;) {
    const [fd, blk] = await Promise.all([provider.getFeeData(), provider.getBlock('latest')]);
    if (blk?.baseFeePerGas == null || !fd?.maxPriorityFeePerGas) { await new Promise((r) => setTimeout(r, 1000)); continue; }
    baseFee = blk.baseFeePerGas;
    tip = fd.maxPriorityFeePerGas + ethers.parseUnits('0.0002', 'gwei');
    if (tip > MAX_FEE_WEI) tip = MAX_FEE_WEI;
    if (baseFee + tip <= MAX_FEE_WEI) break;
    console.error(`· gas too high (${ethers.formatUnits(baseFee + tip, 'gwei')} gwei > ${MAX_GAS_GWEI}) — waiting ${GAS_POLL_S}s`);
    await new Promise((r) => setTimeout(r, GAS_POLL_S * 1000));
  }
  ok(`nonce=${nonce} gasEstimate=${gas} gasLimit=${gasLimit} maxFee=${MAX_GAS_GWEI} gwei tip=${ethers.formatUnits(tip, 'gwei')} gwei`);
  return {
    account_number: SENDER_ACCOUNT, chain: 'ethereum', scheme: 'eth-tx',
    payload: {
      chain_id: CHAIN_ID, nonce, to: CONTRACT, value: '0x0', data: calldata,
      gas_limit: Number(gasLimit),
      max_fee_per_gas: '0x' + MAX_FEE_WEI.toString(16),
      max_priority_fee_per_gas: '0x' + tip.toString(16),
      tx_type: 'eip1559',
    },
  };
}

const [cmd, arg1] = process.argv.slice(2);
const provider = rpc();
const c = new ethers.Contract(CONTRACT, ABI, provider);
const owner = await c.owner();
if (owner.toLowerCase() !== SENDER.toLowerCase()) fail(`senderAddress ${SENDER} is not owner() ${owner} — setTokenBaseURI is onlyOwner`);
ok(`sender is owner (${owner})`);

if (cmd === 'preflight') {
  await sampleChecks(c);
  console.error(`\nready: setTokenBaseURI(${OLD_BASE} → ${NEW_BASE}) — one tx`);
} else if (cmd === 'tx') {
  await sampleChecks(c);
  console.log(JSON.stringify(await vaultTxRequest(provider), null, 2));
} else if (cmd === 'broadcast') {
  if (!arg1) fail('usage: broadcast <vault-tx.json>');
  const txResp = JSON.parse(fs.readFileSync(arg1, 'utf8'));
  if (!txResp.signed_tx) fail(`no signed_tx in ${arg1}`);
  const tx = ethers.Transaction.from(txResp.signed_tx);
  if (tx.chainId !== BigInt(CHAIN_ID)) fail(`chainId ${tx.chainId} ≠ ${CHAIN_ID}. DO NOT RELAY.`);
  if (!tx.to || tx.to.toLowerCase() !== CONTRACT.toLowerCase()) fail(`to ${tx.to} ≠ contract. DO NOT RELAY.`);
  if (tx.value !== 0n) fail('value ≠ 0. DO NOT RELAY.');
  if (tx.data.toLowerCase() !== calldata.toLowerCase()) fail('calldata mismatch. DO NOT RELAY.');
  if (!tx.from || tx.from.toLowerCase() !== SENDER.toLowerCase()) fail(`sender ${tx.from} ≠ ${SENDER}. DO NOT RELAY.`);
  ok(`vault-signed tx verified: from=${tx.from} nonce=${tx.nonce}`);
  await provider.call({ from: tx.from, to: tx.to, data: tx.data, value: 0 });
  ok('final dry-run passed');
  await provider.broadcastTransaction(txResp.signed_tx);
  console.log('tx sent:', tx.hash);
  const rcpt = await provider.waitForTransaction(tx.hash, 2);
  if (!rcpt || rcpt.status !== 1) fail(`tx ${tx.hash} did not succeed`);
  ok(`mined in block ${rcpt.blockNumber}, gasUsed ${rcpt.gasUsed}`);
  const uri = await c.tokenURI(SAMPLES[0]);
  if (uri !== NEW_BASE + SAMPLES[0]) fail(`post-check: tokenURI = ${uri}, expected ${NEW_BASE + SAMPLES[0]}`);
  ok(`post-check: tokenURI(…${SAMPLES[0].slice(-8)}) = ${uri}`);
} else {
  fail('usage: v4-base-uri.mjs preflight | tx | broadcast <vault-tx.json>');
}
