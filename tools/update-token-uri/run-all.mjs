// run-all.mjs — driver: runs update-token-uri.mjs tx → vault sign → broadcast
// in WINDOWS of $TX_WINDOW consecutive nonces (default 10, i.e. up to ~10 txs
// per block), then confirms every tx in the window (2 confs + on-chain re-read)
// before opening the next window. A failure stops the run. TX_WINDOW=1 restores
// the old strictly-sequential behaviour.
//
// Resumable: editions whose on-chain ipfsCID already equals new_metadata_cid
// are skipped by `tx` itself, and progress.json records what was mined.
//
//   VAULT_URL=… VAULT_API_KEY=… RPC_URL=… node run-all.mjs [--only <token_id>,…] [--limit N] [--yes]
//
// Without --yes it prints the plan and waits for Enter before the first tx
// (do a --limit 1 trial first — see README).

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline/promises';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const tool = path.join(scriptDir, 'update-token-uri.mjs');

const args = process.argv.slice(2);
const opt = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : undefined; };
const only = opt('--only')?.split(',').map((s) => s.trim()).filter(Boolean);
const limit = Number(opt('--limit') ?? Infinity);
const yes = args.includes('--yes');

const { VAULT_URL, VAULT_API_KEY } = process.env;
if (!VAULT_URL || !VAULT_API_KEY) { console.error('✗ VAULT_URL and VAULT_API_KEY are required'); process.exit(1); }

const configPath = process.env.UPDATE_CONFIG ?? path.join(scriptDir, 'config.json');
const cfg = JSON.parse(fs.readFileSync(configPath, 'utf8'));
// workDir: where progress.json / txreq-* / vault-tx-* live. Defaults to this
// directory (single-contract use); multi-contract runs set it per config so
// contracts never share a progress file.
const workDir = cfg.workDir ? path.resolve(path.dirname(configPath), cfg.workDir) : scriptDir;
fs.mkdirSync(workDir, { recursive: true });
const progressFile = path.join(workDir, 'progress.json');
const csv = fs.readFileSync(path.resolve(scriptDir, cfg.updates ?? 'updates.csv'), 'utf8').trim().split('\n').slice(1);
// key = token_id (column 2): unique per row. (Editions repeat across the
// several series a contract holds, so they cannot key progress.) --only
// accepts token_ids or, for single-series csvs, edition numbers.
const rows = csv.map((l) => l.split(',').map((s) => s.trim()));
let editions = rows.map((c) => c[1]);
if (only) editions = rows.filter((c) => only.includes(c[1]) || only.includes(c[0])).map((c) => c[1]);
const progress = fs.existsSync(progressFile) ? JSON.parse(fs.readFileSync(progressFile, 'utf8')) : {};
editions = editions.filter((e) => !progress[e]?.txHash).slice(0, limit);

if (editions.length === 0) { console.log('nothing to do'); process.exit(0); }
console.log(`contract ${cfg.contract} — will update ${editions.length} token(s): ${editions.map((t) => '…' + t.slice(-6)).join(' ')}`);
if (!yes) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  await rl.question('press Enter to start (Ctrl-C to abort) ');
  rl.close();
}

const run = (cmdArgs, opts = {}) => spawnSync('node', [tool, ...cmdArgs], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'inherit'], ...opts });

const WINDOW = Math.max(1, Number(process.env.TX_WINDOW ?? 10));

const signAndSend = async (ed, nonce) => {
  // tx (dry-run + vault request; explicit nonce after the first of a window)
  const t = run(['tx', ed, ...(nonce !== undefined ? [String(nonce)] : [])]);
  if (t.status === 3) return { already: true };                 // on-chain already new
  if (t.status !== 0) { console.error(`✗ tx step failed for token …${ed.slice(-8)} — stopping`); process.exit(1); }
  const req = JSON.parse(t.stdout);
  const txreq = path.join(workDir, `txreq-${ed}.json`);
  const vaultResp = path.join(workDir, `vault-tx-${ed}.json`);
  fs.writeFileSync(txreq, t.stdout);
  const res = await fetch(`${VAULT_URL.replace(/\/$/, '')}/sign`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-API-KEY': VAULT_API_KEY }, body: t.stdout,
  });
  const body = await res.text();
  if (!res.ok) { console.error(`✗ vault /sign HTTP ${res.status}: ${body.slice(0, 300)} — stopping`); process.exit(1); }
  fs.writeFileSync(vaultResp, body);
  const b = run(['broadcast', ed, vaultResp, '--no-wait']);
  process.stdout.write(b.stdout);
  if (b.status !== 0) { console.error(`✗ broadcast failed for token …${ed.slice(-8)} — stopping (inspect ${vaultResp}; the nonce may still be free)`); process.exit(1); }
  const txHash = (b.stdout.match(/tx sent: (0x[0-9a-f]{64})/i) ?? [])[1];
  if (!txHash) { console.error('✗ no tx hash from broadcast — stopping'); process.exit(1); }
  return { txHash, nonce: req.payload.nonce, txreq, vaultResp };
};

for (let w = 0; w < editions.length; w += WINDOW) {
  const windowEds = editions.slice(w, w + WINDOW);
  console.log(`\n=== window ${windowEds.length} token(s): ${windowEds.map((t) => '…' + t.slice(-6)).join(' ')} ===`);
  const sent = [];
  let nextNonce;
  for (const ed of windowEds) {
    const r = await signAndSend(ed, nextNonce);
    if (r.already) { progress[ed] = { txHash: 'already-on-chain', at: new Date().toISOString() }; fs.writeFileSync(progressFile, JSON.stringify(progress, null, 2)); continue; }
    nextNonce = r.nonce + 1;                                     // consecutive nonces within the window
    sent.push({ ed, ...r });
  }
  for (const sTx of sent) {                                      // confirm in nonce order; first waits ~1 block, rest are usually instant
    const cRes = run(['confirm', sTx.ed, sTx.txHash]);
    process.stdout.write(cRes.stdout);
    if (cRes.status !== 0) { console.error(`✗ confirm failed for token …${sTx.ed.slice(-8)} (${sTx.txHash}) — stopping; later txs in this window may still mine, re-run to reconcile`); process.exit(1); }
    progress[sTx.ed] = { txHash: sTx.txHash, at: new Date().toISOString() };
    fs.writeFileSync(progressFile, JSON.stringify(progress, null, 2));
    fs.unlinkSync(sTx.txreq); fs.unlinkSync(sTx.vaultResp);
  }
}
console.log(`\ndone: ${editions.length} token(s) updated — run \`node update-token-uri.mjs check\``);
