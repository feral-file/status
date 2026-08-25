// update-tezos-metadata.mjs — repoint FA2 token metadata on a Tezos
// FeralfileExhibitionV2 contract via the trustee-only `update_edition_metadata`
// entrypoint, signing inside autonomy-vault (scheme `tezos-operation`).
//
// Background (feral-file/feral-file#3435): each token's `token_info` holds one
// key `""` → bytes("ipfs://<cid>") pointing at a TZIP-21 JSON. Fixing a broken
// `artifactUri` means pinning a replacement JSON and re-pointing the token.
// The entrypoint takes a LIST, so tokens are updated in batches.
//
// NO LOCAL KEYS. Taquito does counter / estimation / forging / preapply /
// injection; the only thing it cannot do itself is sign, and for that the
// VaultSigner below:
//   1. parses the forged bytes it is handed (local-forging) and REFUSES to
//      sign unless the operation is exactly the batch we built: one
//      transaction, to `contract`, entrypoint `update_edition_metadata`, the
//      expected token ids, amount 0;
//   2. posts `0x03 || forged` to the vault (`tezos-operation`), which
//      blake2b-hashes and Ed25519-signs with the trustee's derived key;
//   3. verifies the vault's `message_hash` against a local blake2b, converts
//      the generic `sig…` to `edsig…`, and hands Taquito the signed bytes.
// The vault's `public_key` must match the trustee's on-chain manager_key.
//
// Commands (see README.md):
//   node update-tezos-metadata.mjs preflight            → trustee check, per-token on-chain vs csv, gateway fetch of every new JSON
//   node update-tezos-metadata.mjs run [--limit N] [--yes]  → batches: estimate, forge, vault-sign, inject, wait 2 confs
//   node update-tezos-metadata.mjs check                → token_info per row vs expected
//
// Config: ./config.json next to this script, or $UPDATE_CONFIG.
// Env:    VAULT_URL, VAULT_API_KEY (run only).

import { TezosToolkit, MichelsonMap } from '@taquito/taquito';
import { LocalForger } from '@taquito/local-forging';
import { b58cdecode, b58cencode, prefix, buf2hex, hex2buf } from '@taquito/utils';
import { hash as blake2b } from '@stablelib/blake2b';
import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline/promises';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const configPath = process.env.UPDATE_CONFIG ?? path.join(scriptDir, 'config.json');
const progressFile = path.join(scriptDir, 'progress.json');

function fail(msg) { console.error('✗', msg); process.exit(1); }
function ok(msg)   { console.error('✓', msg); }

if (!fs.existsSync(configPath)) fail(`config not found: ${configPath} — copy config.example.json to config.json`);
const cfg = JSON.parse(fs.readFileSync(configPath, 'utf8'));
const RPC = cfg.rpcUrl ?? 'https://rpc.tzkt.io/mainnet';
const CONTRACT = cfg.contract;
const SENDER = cfg.senderAddress;
const SENDER_ACCOUNT = cfg.senderAccount;
const GATEWAY = (cfg.metadataGateway ?? 'https://ipfs.feralfile.com/ipfs/').replace(/\/?$/, '/');
const BATCH = Number(cfg.batchSize ?? 20);
if (!/^KT1[1-9A-HJ-NP-Za-km-z]{33}$/.test(CONTRACT ?? '')) fail('config: contract must be a KT1 address');
if (!/^tz[123][1-9A-HJ-NP-Za-km-z]{33}$/.test(SENDER ?? '')) fail('config: senderAddress must be the trustee tz address');
if (!SENDER_ACCOUNT || SENDER_ACCOUNT.startsWith('FILL')) fail('config: senderAccount must be the vault account identifier');
if (!(BATCH >= 1 && BATCH <= 100)) fail('config: batchSize must be 1..100');

// updates csv: token_id,old_metadata_cid,new_metadata_cid  (feralverse-metadata-fix/pin.sh output)
const updatesPath = path.resolve(scriptDir, cfg.updates ?? 'updates.csv');
if (!fs.existsSync(updatesPath)) fail(`updates csv not found: ${updatesPath}`);
const CID_RE = /^(Qm[1-9A-HJ-NP-Za-km-z]{44}|bafy[a-z2-7]{55,})$/;
const UPDATES = fs.readFileSync(updatesPath, 'utf8').trim().split('\n').slice(1).filter(Boolean).map((line) => {
  const [tokenId, oldCid, newCid] = line.split(',').map((s) => s.trim());
  if (!/^\d+$/.test(tokenId)) fail(`bad token_id in updates csv: ${line}`);
  if (!CID_RE.test(oldCid) || !CID_RE.test(newCid)) fail(`bad cid in updates csv: ${line}`);
  return { tokenId, oldCid, newCid, oldUri: `ipfs://${oldCid}`, newUri: `ipfs://${newCid}` };
});
if (UPDATES.length === 0) fail('updates csv has no rows');
if (new Set(UPDATES.map((u) => u.tokenId)).size !== UPDATES.length) fail('updates csv: duplicate token_id');

const args = process.argv.slice(2);
const cmd = args[0];
const opt = (n) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : undefined; };

const utf8Hex = (s) => buf2hex(Buffer.from(s, 'utf8'));
const hexUtf8 = (h) => Buffer.from(h, 'hex').toString('utf8');

// ---------------------------------------------------------------------------
// Chain reads

const Tezos = new TezosToolkit(RPC);
const forger = new LocalForger();

async function loadContract() {
  const c = await Tezos.contract.at(CONTRACT);
  const st = await c.storage();
  const trustees = (st.trustee?.trustees ?? []).map(String);
  const admin = String(st.admin?.admin ?? '');
  if (!trustees.includes(SENDER)) fail(`senderAddress ${SENDER} is not a trustee (${trustees.join(', ')}) — update_edition_metadata reverts FF_NOT_TRUSTEE`);
  ok(`sender ${SENDER} is a trustee (admin ${admin})`);
  return { c, st };
}

async function currentUri(st, tokenId) {
  const row = await st.assets.token_metadata.get(tokenId);
  if (!row) return null;
  const info = row.token_info;
  const hex = info.get ? info.get('') : info[''];
  return hex ? hexUtf8(hex) : null;
}

async function gatewayCheck(u) {
  const url = `${GATEWAY}${u.newCid}`;
  let res;
  try { res = await fetch(url, { signal: AbortSignal.timeout(60_000) }); }
  catch (e) { return { okay: false, why: `fetch failed: ${e.message}` }; }
  if (!res.ok) return { okay: false, why: `HTTP ${res.status}` };
  let m;
  try { m = await res.json(); } catch { return { okay: false, why: 'not JSON' }; }
  if (typeof m.artifactUri !== 'string' || !m.artifactUri.startsWith('ipfs://')) return { okay: false, why: `artifactUri is ${JSON.stringify(m.artifactUri)}` };
  const f0 = Array.isArray(m.formats) ? m.formats[0] : null;
  if (!f0 || f0.uri !== m.artifactUri || f0.mimeType !== 'video/mp4') return { okay: false, why: `formats[0] is ${JSON.stringify(f0)}` };
  return { okay: true, why: `artifactUri=${m.artifactUri.slice(7, 19)}… ${f0.mimeType}` };
}

// ---------------------------------------------------------------------------
// Vault-backed signer (Taquito Signer interface)

class VaultSigner {
  constructor(pkh, pk, batch) { this.pkh = pkh; this.pk = pk; this.batch = batch; }
  async publicKeyHash() { return this.pkh; }
  async publicKey() { return this.pk; }
  async secretKey() { throw new Error('no local secret key'); }
  async sign(bytes, magicByte) {
    // 1. Refuse anything that is not exactly our batch.
    if (!magicByte || buf2hex(magicByte) !== '03') throw new Error(`refusing to sign: watermark ${magicByte ? buf2hex(magicByte) : 'none'} ≠ 03 (generic operation)`);
    const parsed = await forger.parse(bytes);
    const txs = parsed.contents.filter((c) => c.kind === 'transaction');
    const others = parsed.contents.filter((c) => c.kind !== 'transaction' && c.kind !== 'reveal');
    if (others.length) throw new Error(`refusing to sign: unexpected operation kinds ${others.map((o) => o.kind).join(',')}`);
    if (txs.length !== 1) throw new Error(`refusing to sign: expected 1 transaction, got ${txs.length}`);
    const tx = txs[0];
    if (tx.source !== this.pkh) throw new Error(`refusing to sign: source ${tx.source} ≠ ${this.pkh}`);
    if (tx.destination !== CONTRACT) throw new Error(`refusing to sign: destination ${tx.destination} ≠ ${CONTRACT}`);
    if (String(tx.amount) !== '0') throw new Error(`refusing to sign: amount ${tx.amount} ≠ 0`);
    if (tx.parameters?.entrypoint !== 'update_edition_metadata') throw new Error(`refusing to sign: entrypoint ${tx.parameters?.entrypoint}`);
    // parameters.value is Micheline: list of Pair(nat, map{ Elt(string, bytes) })
    const items = tx.parameters.value;
    if (!Array.isArray(items) || items.length !== this.batch.length) throw new Error(`refusing to sign: ${items?.length} items ≠ batch ${this.batch.length}`);
    items.forEach((it, i) => {
      const u = this.batch[i];
      const tokenId = it.args?.[0]?.int;
      const elts = it.args?.[1];
      if (tokenId !== u.tokenId) throw new Error(`refusing to sign: item ${i} token ${tokenId} ≠ ${u.tokenId}`);
      if (!Array.isArray(elts) || elts.length !== 1) throw new Error(`refusing to sign: item ${i} token_info has ${elts?.length} keys, expected 1`);
      const key = elts[0].args?.[0]?.string; const val = elts[0].args?.[1]?.bytes;
      if (key !== '' || val?.toLowerCase() !== utf8Hex(u.newUri)) throw new Error(`refusing to sign: item ${i} token_info mismatch (${key} → ${val})`);
    });
    ok(`forged bytes verified: 1 tx → ${CONTRACT} update_edition_metadata × ${items.length}, source ${this.pkh}, amount 0`);
    // 2. Vault signs 0x03 || bytes.
    const forgedWithWatermark = '03' + bytes;
    const localDigest = buf2hex(blake2b(hex2buf(forgedWithWatermark), 32));
    const res = await fetch(`${process.env.VAULT_URL.replace(/\/$/, '')}/sign`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-API-KEY': process.env.VAULT_API_KEY },
      body: JSON.stringify({ account_number: SENDER_ACCOUNT, chain: 'tezos', scheme: 'tezos-operation', payload: { forged_op_bytes: '0x' + forgedWithWatermark } }),
    });
    const body = await res.text();
    if (!res.ok) throw new Error(`vault /sign HTTP ${res.status}: ${body.slice(0, 300)}`);
    const r = JSON.parse(body);
    // 3. Verify what came back.
    if ((r.message_hash ?? '').replace(/^0x/, '').toLowerCase() !== localDigest) throw new Error(`vault message_hash ${r.message_hash} ≠ local blake2b ${localDigest}. DO NOT INJECT.`);
    if (r.public_key !== this.pk) throw new Error(`vault public_key ${r.public_key} ≠ on-chain manager_key ${this.pk}. DO NOT INJECT.`);
    if (!r.signature?.startsWith('sig')) throw new Error(`unexpected signature format ${r.signature?.slice(0, 6)}`);
    const raw = b58cdecode(r.signature, prefix.sig);       // 64 bytes
    if (raw.length !== 64) throw new Error(`signature is ${raw.length} bytes`);
    const edsig = b58cencode(raw, prefix.edsig);
    ok(`vault signature verified (message_hash parity, public_key parity)`);
    return { bytes, sig: buf2hex(raw), prefixSig: edsig, sbytes: bytes + buf2hex(raw) };
  }
}

// Read-only signer for `estimate` (Taquito needs a public key for simulation).
class ReadOnlySigner {
  constructor(pkh, pk) { this.pkh = pkh; this.pk = pk; }
  async publicKeyHash() { return this.pkh; }
  async publicKey() { return this.pk; }
  async secretKey() { throw new Error('read-only'); }
  async sign() { throw new Error('read-only signer'); }
}

async function managerKey() {
  const pk = await Tezos.rpc.getManagerKey(SENDER);
  const key = typeof pk === 'string' ? pk : pk?.key;
  if (!key) fail(`${SENDER} has no revealed public key on-chain`);
  return key;
}

const paramFor = (batch) => batch.map((u) => ({ token_id: u.tokenId, token_info: MichelsonMap.fromLiteral({ '': utf8Hex(u.newUri) }) }));

// ---------------------------------------------------------------------------

if (cmd === 'preflight') {
  const { st } = await loadContract();
  let todo = 0, done = 0, blocked = 0;
  for (const u of UPDATES) {
    const cur = await currentUri(st, u.tokenId);
    if (cur === null) { blocked++; console.log(`…${u.tokenId.slice(-8)}  BLOCKED  no token_metadata row`); continue; }
    if (cur === u.newUri) { done++; console.log(`…${u.tokenId.slice(-8)}  DONE     already ${u.newUri}`); continue; }
    if (cur !== u.oldUri) { blocked++; console.log(`…${u.tokenId.slice(-8)}  BLOCKED  on-chain ${cur} ≠ csv old ${u.oldUri} — csv is stale`); continue; }
    const gw = await gatewayCheck(u);
    if (!gw.okay) { blocked++; console.log(`…${u.tokenId.slice(-8)}  BLOCKED  new metadata not servable: ${gw.why} (${GATEWAY}${u.newCid})`); continue; }
    todo++; console.log(`…${u.tokenId.slice(-8)}  TODO     ${u.oldCid} → ${u.newCid}  (${gw.why})`);
  }
  if (todo) {
    // Simulate the first batch as the trustee (no signature needed).
    const pk = await managerKey();
    Tezos.setSignerProvider(new ReadOnlySigner(SENDER, pk));
    const { c } = await loadContract();
    const first = UPDATES.filter((u) => true).slice(0, BATCH);
    const est = await Tezos.estimate.transfer(c.methodsObject.update_edition_metadata(paramFor(first)).toTransferParams());
    ok(`simulation of a ${first.length}-token batch: gas ${est.gasLimit}, storage ${est.storageLimit}, fee ${est.suggestedFeeMutez} mutez`);
  }
  console.error(`\n${todo} to do · ${done} already done · ${blocked} blocked`);
  if (blocked) process.exit(2);

} else if (cmd === 'run') {
  if (!process.env.VAULT_URL || !process.env.VAULT_API_KEY) fail('VAULT_URL and VAULT_API_KEY are required');
  const limit = Number(opt('--limit') ?? Infinity);
  const yes = args.includes('--yes');
  const pk = await managerKey();
  // The vault must hold the same key the chain knows for the trustee.
  const acct = await fetch(`${process.env.VAULT_URL.replace(/\/$/, '')}/accounts/${encodeURIComponent(SENDER_ACCOUNT)}`, { headers: { 'X-API-KEY': process.env.VAULT_API_KEY } });
  if (!acct.ok) fail(`vault /accounts/${SENDER_ACCOUNT} HTTP ${acct.status}`);
  const a = await acct.json();
  if (a.tezos_address !== SENDER) fail(`vault account ${SENDER_ACCOUNT} is ${a.tezos_address}, config senderAddress is ${SENDER}`);
  if (a.tezos_public_key !== pk) fail(`vault tezos_public_key ${a.tezos_public_key} ≠ on-chain manager_key ${pk}`);
  ok(`vault account ${SENDER_ACCOUNT} = ${SENDER} (public key matches chain)`);
  const { c, st } = await loadContract();
  const progress = fs.existsSync(progressFile) ? JSON.parse(fs.readFileSync(progressFile, 'utf8')) : {};
  const pending = [];
  for (const u of UPDATES) {
    if (progress[u.tokenId]?.opHash) continue;
    const cur = await currentUri(st, u.tokenId);
    if (cur === u.newUri) continue;
    if (cur !== u.oldUri) fail(`…${u.tokenId.slice(-8)}: on-chain ${cur} ≠ csv old ${u.oldUri} — run preflight`);
    pending.push(u);
  }
  const todo = pending.slice(0, limit);
  if (!todo.length) { console.log('nothing to do'); process.exit(0); }
  const batches = [];
  for (let i = 0; i < todo.length; i += BATCH) batches.push(todo.slice(i, i + BATCH));
  console.log(`will update ${todo.length} token(s) in ${batches.length} batch(es) of ≤${BATCH} from ${SENDER}`);
  if (!yes) {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    await rl.question('press Enter to start (Ctrl-C to abort) ');
    rl.close();
  }
  for (const [bi, batch] of batches.entries()) {
    console.log(`\n=== batch ${bi + 1}/${batches.length}: ${batch.length} tokens (…${batch[0].tokenId.slice(-6)} … …${batch[batch.length - 1].tokenId.slice(-6)})`);
    for (const u of batch) { const gw = await gatewayCheck(u); if (!gw.okay) fail(`…${u.tokenId.slice(-8)}: new metadata not servable: ${gw.why}`); }
    Tezos.setSignerProvider(new VaultSigner(SENDER, pk, batch));
    const op = await c.methodsObject.update_edition_metadata(paramFor(batch)).send();
    console.log('op hash:', op.hash);
    await op.confirmation(2);
    const result = op.results?.[0]?.metadata?.operation_result ?? op.operationResults?.[0]?.metadata?.operation_result;
    const status = result?.status ?? 'unknown';
    if (status !== 'applied') fail(`op ${op.hash} status ${status} — stopping`);
    ok(`applied in block ${op.includedInBlock}, consumed gas ${result?.consumed_milligas ?? '?'} milligas`);
    // Post-check every token in the batch against fresh storage.
    const st2 = await c.storage();
    for (const u of batch) {
      const cur = await currentUri(st2, u.tokenId);
      if (cur !== u.newUri) fail(`post-check: …${u.tokenId.slice(-8)} is ${cur}, expected ${u.newUri}`);
      progress[u.tokenId] = { opHash: op.hash, at: new Date().toISOString() };
    }
    fs.writeFileSync(progressFile, JSON.stringify(progress, null, 2));
    ok(`post-check: ${batch.length}/${batch.length} tokens now point at their new metadata`);
  }
  console.log(`\ndone: ${todo.length} token(s) updated — run \`node update-tezos-metadata.mjs check\``);

} else if (cmd === 'check') {
  const c = await Tezos.contract.at(CONTRACT);
  const st = await c.storage();
  let good = 0;
  for (const u of UPDATES) {
    const cur = await currentUri(st, u.tokenId);
    const mark = cur === u.newUri ? 'UPDATED ✓' : cur === u.oldUri ? 'old' : 'OTHER ⚠';
    if (cur === u.newUri) good++;
    console.log(`…${u.tokenId.slice(-8)}  ${cur}  ${mark}`);
  }
  console.error(`${good}/${UPDATES.length} updated`);

} else {
  fail('usage: update-tezos-metadata.mjs preflight | run [--limit N] [--yes] | check');
}
