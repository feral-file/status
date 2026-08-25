// run-all.mjs — driver: runs update-token-uri.mjs tx → vault sign → broadcast
// for every edition in the updates csv, strictly one at a time (each tx has
// its own nonce; a failure stops the run so nothing lands out of order).
//
// Resumable: editions whose on-chain ipfsCID already equals new_metadata_cid
// are skipped by `tx` itself, and progress.json records what was mined.
//
//   VAULT_URL=… VAULT_API_KEY=… RPC_URL=… node run-all.mjs [--only 23,24] [--limit N] [--yes]
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
const progressFile = path.join(scriptDir, 'progress.json');

const args = process.argv.slice(2);
const opt = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : undefined; };
const only = opt('--only')?.split(',').map((s) => s.trim()).filter(Boolean);
const limit = Number(opt('--limit') ?? Infinity);
const yes = args.includes('--yes');

const { VAULT_URL, VAULT_API_KEY } = process.env;
if (!VAULT_URL || !VAULT_API_KEY) { console.error('✗ VAULT_URL and VAULT_API_KEY are required'); process.exit(1); }

const cfg = JSON.parse(fs.readFileSync(process.env.UPDATE_CONFIG ?? path.join(scriptDir, 'config.json'), 'utf8'));
const csv = fs.readFileSync(path.resolve(scriptDir, cfg.updates ?? 'updates.csv'), 'utf8').trim().split('\n').slice(1);
let editions = csv.map((l) => l.split(',')[0].trim());
if (only) editions = editions.filter((e) => only.includes(e));
const progress = fs.existsSync(progressFile) ? JSON.parse(fs.readFileSync(progressFile, 'utf8')) : {};
editions = editions.filter((e) => !progress[e]?.txHash).slice(0, limit);

if (editions.length === 0) { console.log('nothing to do'); process.exit(0); }
console.log(`will update ${editions.length} edition(s): ${editions.join(' ')}`);
if (!yes) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  await rl.question('press Enter to start (Ctrl-C to abort) ');
  rl.close();
}

const run = (cmdArgs, opts = {}) => spawnSync('node', [tool, ...cmdArgs], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'inherit'], ...opts });

for (const ed of editions) {
  console.log(`\n=== edition ${ed} ===`);
  const txreq = path.join(scriptDir, `txreq-${ed}.json`);
  const vaultResp = path.join(scriptDir, `vault-tx-${ed}.json`);

  const t = run(['tx', ed]);
  if (t.status !== 0) { console.error(`✗ tx step failed for edition ${ed} — stopping`); process.exit(1); }
  fs.writeFileSync(txreq, t.stdout);

  const res = await fetch(`${VAULT_URL.replace(/\/$/, '')}/sign`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-API-KEY': VAULT_API_KEY }, body: t.stdout,
  });
  const body = await res.text();
  if (!res.ok) { console.error(`✗ vault /sign HTTP ${res.status}: ${body.slice(0, 300)} — stopping`); process.exit(1); }
  fs.writeFileSync(vaultResp, body);

  const b = run(['broadcast', ed, vaultResp]);
  process.stdout.write(b.stdout);
  if (b.status !== 0) { console.error(`✗ broadcast failed for edition ${ed} — stopping (inspect ${vaultResp}; the nonce may still be free)`); process.exit(1); }
  const txHash = (b.stdout.match(/tx sent: (0x[0-9a-f]{64})/i) ?? [])[1];
  progress[ed] = { txHash, at: new Date().toISOString() };
  fs.writeFileSync(progressFile, JSON.stringify(progress, null, 2));
  fs.unlinkSync(txreq); fs.unlinkSync(vaultResp); // signed tx is mined; nothing to keep
}
console.log(`\ndone: ${editions.length} edition(s) updated — run \`node update-token-uri.mjs check\``);
