#!/usr/bin/env node
// feralfile-keep — give it your wallet address, get your Feral File library
// pinned on your own IPFS node.
//
// This is the command-line twin of the wallet lookup on status.feralfile.com
// (static/wallet.js in this repo). It uses the same keyless public indexers
// for holdings (Blockscout for Ethereum, TzKT for Tezos) and the same
// published data for the join (work_index.json + per-exhibition shards,
// fetched at runtime — never bundled, so the answer is as current as the
// site). The one thing it adds is the last mile: talking to a local kubo
// node so the files actually land on disk you control.
//
// Zero dependencies, global fetch, Node >= 18.

import { writeFileSync } from "node:fs";

const BLOCKSCOUT = "https://eth.blockscout.com/api/v2";
const TZKT = "https://api.tzkt.io/v1";
const PAGE_CAP = 400; // indexer pages; 400 x 1000 rows is plenty
const TZKT_LIMIT = 1000;
const DEFAULT_STATUS_URL = "https://status.feralfile.com";
const DEFAULT_API = "http://127.0.0.1:5001";
const SHARD_CONCURRENCY = 8;
const DEFAULT_PIN_DEADLINE_MS = 15 * 60 * 1000;

const USAGE = `feralfile-keep <address...> [options]

Pins every published Feral File work held by the given wallet address(es)
to your local IPFS node.

Addresses
  0x…            Ethereum (40 hex characters)
  tz1/tz2/tz3…   Tezos

Options
  --dry-run            enumerate and report, pin nothing
  --api <url>          kubo HTTP API (default ${DEFAULT_API})
  --timeout <seconds>  per-pin timeout handed to the node
  --out <file>         also write the unique CID list, one per line
  --status-url <url>   published data source (default ${DEFAULT_STATUS_URL})
  -h, --help           this text

Boundaries
  Bitmark-era works cannot be enumerated from a wallet address. Look those
  up by token ID on ${DEFAULT_STATUS_URL} instead.
`;

// ---------------------------------------------------------------- arguments

function parseArgs(argv) {
  const opts = {
    addresses: [],
    dryRun: false,
    api: DEFAULT_API,
    statusUrl: DEFAULT_STATUS_URL,
    timeout: null,
    out: null,
    help: false,
  };
  const needsValue = new Set(["--api", "--timeout", "--out", "--status-url"]);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "-h" || a === "--help") {
      opts.help = true;
    } else if (a === "--dry-run") {
      opts.dryRun = true;
    } else if (needsValue.has(a)) {
      const v = argv[++i];
      if (v === undefined) fail(`${a} needs a value.`);
      if (a === "--api") opts.api = v.replace(/\/+$/, "");
      else if (a === "--status-url") opts.statusUrl = v.replace(/\/+$/, "");
      else if (a === "--out") opts.out = v;
      else if (a === "--timeout") {
        const n = Number(v);
        if (!Number.isFinite(n) || n <= 0) fail(`--timeout wants a positive number of seconds, got "${v}".`);
        opts.timeout = n;
      }
    } else if (a.startsWith("-")) {
      fail(`Unknown option "${a}". Run with --help.`);
    } else {
      opts.addresses.push(a);
    }
  }
  return opts;
}

class CliError extends Error {}

function fail(msg) {
  throw new CliError(msg);
}

function detectWallet(q) {
  if (/^0x[0-9a-fA-F]{40}$/.test(q)) return "eth";
  if (/^(tz1|tz2|tz3)[1-9A-HJ-NP-Za-km-z]{33}$/.test(q)) return "tezos";
  return null;
}

// ------------------------------------------------------------------ helpers

function shortCid(c) {
  return c.length > 20 ? c.slice(0, 12) + "…" + c.slice(-6) : c;
}

function humanBytes(n) {
  if (!Number.isFinite(n)) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let u = 0;
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024;
    u++;
  }
  return (u === 0 ? v : v.toFixed(v < 10 ? 1 : 0)) + " " + units[u];
}

function plural(n, one, many) {
  return n === 1 ? one : many !== undefined ? many : one + "s";
}

// Progress that overwrites itself on a TTY and stays quiet on a pipe.
const isTTY = process.stdout.isTTY;
let progressLive = false;
function progress(msg) {
  if (!isTTY) return;
  process.stdout.write("\r\x1b[2K  " + msg);
  progressLive = true;
}
function progressDone() {
  if (progressLive) {
    process.stdout.write("\r\x1b[2K");
    progressLive = false;
  }
}
function say(line = "") {
  progressDone();
  console.log(line);
}

async function getJson(url, tries = 3) {
  let lastErr;
  for (let attempt = 0; attempt < tries; attempt++) {
    try {
      const r = await fetch(url, { headers: { accept: "application/json" } });
      if (r.status === 404) return { notFound: true };
      if (!r.ok) throw new Error("HTTP " + r.status);
      return { data: await r.json() };
    } catch (e) {
      lastErr = e;
      if (attempt < tries - 1) await sleep(500 * (attempt + 1));
    }
  }
  throw lastErr;
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

// ---------------------------------------------------------------- enumerate

async function fetchEthHoldings(addr) {
  const held = [];
  let extra = "";
  for (let page = 0; page < PAGE_CAP; page++) {
    const { data, notFound } = await getJson(
      `${BLOCKSCOUT}/addresses/${addr}/nft?type=ERC-721%2CERC-1155${extra}`
    );
    if (notFound) return held; // address never seen on chain
    for (const it of data.items || []) {
      if (it.id && it.token && it.token.address_hash) {
        held.push({ contract: it.token.address_hash, tokenId: String(it.id) });
      }
    }
    progress(`reading Ethereum holdings from Blockscout — ${held.length} tokens…`);
    if (!data.next_page_params) return held;
    extra = "&" + new URLSearchParams(data.next_page_params).toString();
  }
  return held;
}

async function fetchTezosHoldings(addr) {
  const held = [];
  for (let page = 0; page < PAGE_CAP; page++) {
    const { data: rows } = await getJson(
      `${TZKT}/tokens/balances?account=${addr}&balance.gt=0&limit=${TZKT_LIMIT}` +
        `&offset=${page * TZKT_LIMIT}&select=token.contract.address,token.tokenId`
    );
    for (const row of rows) {
      const contract = row["token.contract.address"];
      const tokenId = row["token.tokenId"];
      if (contract && tokenId != null) held.push({ contract, tokenId: String(tokenId) });
    }
    progress(`reading Tezos holdings from TzKT — ${held.length} token balances…`);
    if (rows.length < TZKT_LIMIT) return held;
  }
  return held;
}

// --------------------------------------------------------- published census

function makeCensus(statusUrl) {
  let indexPromise = null;
  const shardCache = new Map();
  return {
    index() {
      if (!indexPromise) {
        indexPromise = getJson(`${statusUrl}/data/work_index.json`).then((r) => {
          if (r.notFound || !r.data) throw new Error("work_index.json unavailable");
          return r.data;
        });
      }
      return indexPromise;
    },
    shard(exId) {
      if (!shardCache.has(exId)) {
        shardCache.set(
          exId,
          getJson(`${statusUrl}/data/works/${exId}.json`).then((r) => {
            if (r.notFound || !r.data) throw new Error(`shard ${exId} unavailable`);
            return r.data;
          })
        );
      }
      return shardCache.get(exId);
    },
  };
}

function sameContract(kind, a, b) {
  return kind === "eth" ? a.toLowerCase() === b.toLowerCase() : a === b;
}

// Join held (contract, tokenId) pairs against the published shards.
// One record per matched work entry — the same join static/wallet.js runs.
async function matchHoldings(held, kind, census) {
  const index = await census.index();
  const seen = new Set();
  const candidates = [];
  for (const h of held) {
    const key = h.contract + "/" + h.tokenId;
    if (seen.has(key)) continue;
    seen.add(key);
    if (index[h.tokenId]) candidates.push(h);
  }
  progress(`checking ${candidates.length} candidate ${plural(candidates.length, "work")} against the census…`);

  const exIds = [...new Set(candidates.flatMap((h) => index[h.tokenId]))];
  const shards = new Map();
  for (let i = 0; i < exIds.length; i += SHARD_CONCURRENCY) {
    const batch = exIds.slice(i, i + SHARD_CONCURRENCY);
    await Promise.all(
      batch.map((id) => census.shard(id).then((s) => shards.set(id, s)))
    );
    progress(
      `loading published data — ${shards.size}/${exIds.length} ${plural(exIds.length, "exhibition")}…`
    );
  }

  const matches = [];
  for (const h of candidates) {
    for (const exId of index[h.tokenId]) {
      const shard = shards.get(exId);
      for (const entry of (shard && shard.works[h.tokenId]) || []) {
        if (sameContract(kind, entry.contract || "", h.contract)) {
          matches.push({ tokenId: h.tokenId, exhibition: shard.exhibition, entry });
        }
      }
    }
  }
  return { matches, dedupedHeld: seen.size };
}

function pinnableCids(entry) {
  const out = [];
  for (const f of entry.files || []) {
    if (f.cid && (f.host === "ipfs" || f.host === "ipfs-archival")) {
      out.push({ cid: f.cid, wholeSeries: f.host === "ipfs-archival" });
    }
  }
  return out;
}

function workLabel(m) {
  return m.entry.name ? m.entry.name : "token …" + m.tokenId.slice(-8);
}

// ------------------------------------------------------------------- pinning

async function ipfsPost(api, path, opts = {}) {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), opts.deadlineMs || 30000);
  try {
    const r = await fetch(api + path, { method: "POST", signal: ac.signal });
    const text = await r.text();
    if (!r.ok) {
      let msg = `HTTP ${r.status}`;
      try {
        const j = JSON.parse(text);
        if (j.Message) msg = j.Message;
      } catch {}
      throw new Error(msg);
    }
    return text ? JSON.parse(text) : {};
  } finally {
    clearTimeout(t);
  }
}

async function apiReachable(api) {
  try {
    await ipfsPost(api, "/api/v0/version", { deadlineMs: 5000 });
    return true;
  } catch {
    return false;
  }
}

async function pinCid(api, cid, timeoutSec) {
  const t = timeoutSec ? `&timeout=${timeoutSec}s` : "";
  // Give the client a little more rope than the node, so a node-side timeout
  // reports as a timeout rather than as a torn connection.
  const deadlineMs = timeoutSec ? timeoutSec * 1000 + 15000 : DEFAULT_PIN_DEADLINE_MS;
  await ipfsPost(api, `/api/v0/pin/add?arg=${encodeURIComponent(cid)}&recursive=true${t}`, {
    deadlineMs,
  });
}

async function cidSize(api, cid) {
  try {
    const j = await ipfsPost(api, `/api/v0/files/stat?arg=/ipfs/${encodeURIComponent(cid)}`, {
      deadlineMs: 30000,
    });
    const n = j.CumulativeSize ?? j.Size;
    return Number.isFinite(n) ? n : null;
  } catch {
    return null; // size is a nicety, never a failure
  }
}

function isTimeout(err) {
  const m = String((err && err.message) || err).toLowerCase();
  return m.includes("timeout") || m.includes("abort") || m.includes("deadline");
}

// ---------------------------------------------------------------------- main

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help || opts.addresses.length === 0) {
    console.log(USAGE);
    process.exitCode = opts.help ? 0 : 2;
    return;
  }

  const wallets = [];
  for (const a of opts.addresses) {
    const kind = detectWallet(a);
    if (!kind) {
      fail(
        `"${a}" is not an address this understands.\n` +
          "  Ethereum looks like 0x followed by 40 hex characters.\n" +
          "  Tezos looks like tz1/tz2/tz3 followed by 33 base58 characters.\n" +
          "  A 64-character Bitmark token ID is not a wallet — look those up\n" +
          `  by token ID on ${opts.statusUrl}.`
      );
    }
    wallets.push({ address: a, kind });
  }

  const census = makeCensus(opts.statusUrl);
  say("feralfile-keep — your Feral File library, pinned where you can reach it.");
  say(`Published data: ${opts.statusUrl}`);

  // CID -> {wholeSeries, works:Set<label>}
  const cidMap = new Map();
  let totalMatches = 0;
  let totalUnpinnable = 0;

  for (const w of wallets) {
    const chainName = w.kind === "eth" ? "Ethereum" : "Tezos";
    say();
    say(`Wallet ${w.address}  (${chainName})`);
    let held;
    try {
      held =
        w.kind === "eth"
          ? await fetchEthHoldings(w.address)
          : await fetchTezosHoldings(w.address);
    } catch (e) {
      progressDone();
      say(`  could not read holdings: ${e.message}`);
      say(`  (${w.kind === "eth" ? "Blockscout" : "TzKT"} may be briefly unavailable — try again.)`);
      w.error = true;
      continue;
    }

    let matches, dedupedHeld;
    try {
      ({ matches, dedupedHeld } = await matchHoldings(held, w.kind, census));
    } catch (e) {
      progressDone();
      say(`  could not load published data: ${e.message}`);
      w.error = true;
      continue;
    }
    progressDone();

    say(
      `  ${held.length.toLocaleString()} ${plural(held.length, "token")} held ` +
        `(${dedupedHeld.toLocaleString()} unique) · ` +
        `${matches.length} published Feral File ${plural(matches.length, "work")} matched`
    );

    const withCids = [];
    const withoutCids = [];
    for (const m of matches) {
      const cids = pinnableCids(m.entry);
      (cids.length ? withCids : withoutCids).push({ m, cids });
      for (const c of cids) {
        const rec = cidMap.get(c.cid) || { wholeSeries: c.wholeSeries, works: new Set() };
        rec.wholeSeries = rec.wholeSeries || c.wholeSeries;
        rec.works.add(workLabel(m));
        cidMap.set(c.cid, rec);
      }
    }
    totalMatches += matches.length;
    totalUnpinnable += withoutCids.length;

    if (matches.length) say();
    for (const { m, cids } of [...withCids, ...withoutCids]) {
      const ex = m.exhibition.title || m.exhibition.slug || "exhibition";
      let tail;
      if (cids.length) {
        const series = cids.filter((c) => c.wholeSeries).length;
        tail =
          `${cids.length} pinnable ${plural(cids.length, "file")}` +
          (series ? ` (${series} whole-series archival — large)` : "");
      } else {
        tail = "nothing to pin yet";
      }
      say(`  ${ex} — ${workLabel(m)} — ${tail}`);
    }
    if (!matches.length) {
      say("  No published Feral File works found for this address.");
    }
  }

  const cids = [...cidMap.keys()];

  say();
  if (opts.out) {
    writeFileSync(opts.out, cids.length ? cids.join("\n") + "\n" : "");
    say(`Wrote ${cids.length} ${plural(cids.length, "CID")} to ${opts.out}`);
  }

  if (!cids.length) {
    say("Nothing to pin.");
    printBoundaries(totalUnpinnable, opts);
    process.exitCode = wallets.some((w) => w.error) ? 1 : 0;
    return;
  }

  const seriesCount = [...cidMap.values()].filter((r) => r.wholeSeries).length;
  say(
    `${cids.length} unique content ${plural(cids.length, "address", "addresses")} to pin` +
      (seriesCount ? ` (${seriesCount} whole-series archival — large)` : "") +
      " — editions of the same work share files."
  );

  if (opts.dryRun) {
    say();
    say("Dry run — nothing was pinned. These would be:");
    for (const cid of cids) {
      const rec = cidMap.get(cid);
      say(`  ${cid}${rec.wholeSeries ? "  (whole-series archival — large)" : ""}`);
    }
    printBoundaries(totalUnpinnable, opts);
    process.exitCode = wallets.some((w) => w.error) ? 1 : 0;
    return;
  }

  // Pin phase.
  say();
  if (!(await apiReachable(opts.api))) {
    const file = opts.out || "feralfile-pins.txt";
    writeFileSync(file, cids.join("\n") + "\n");
    say(`No IPFS node answering at ${opts.api}.`);
    say(`Wrote the pin list to ${file} instead. When your node is running:`);
    say();
    say(`  xargs -n1 ipfs pin add < ${file}`);
    say();
    say("(Start a node with `ipfs daemon`, or point this at another one with --api.)");
    printBoundaries(totalUnpinnable, opts);
    return;
  }

  say(`Pinning ${cids.length} unique ${plural(cids.length, "CID")} to ${opts.api}` +
    (opts.timeout ? ` (${opts.timeout}s per pin)` : "") + "…");
  say();

  let pinned = 0;
  let failed = 0;
  let bytes = 0;
  let n = 0;
  for (const cid of cids) {
    n++;
    const rec = cidMap.get(cid);
    progress(`[${n}/${cids.length}] pinning ${shortCid(cid)}…`);
    const started = Date.now();
    try {
      await pinCid(opts.api, cid, opts.timeout);
      const size = await cidSize(opts.api, cid);
      if (size != null) bytes += size;
      pinned++;
      progressDone();
      say(
        `  ok      ${cid}  ${size != null ? humanBytes(size) : "size unknown"}` +
          (rec.wholeSeries ? "  (whole series)" : "")
      );
    } catch (e) {
      failed++;
      progressDone();
      const secs = ((Date.now() - started) / 1000).toFixed(0);
      const why = isTimeout(e) ? `timeout after ${secs}s` : e.message;
      say(`  FAIL    ${cid}  ${why}` + (rec.wholeSeries ? "  (whole series)" : ""));
    }
  }
  progressDone();

  say();
  say("Summary");
  say(`  works matched   ${totalMatches}`);
  say(`  unique CIDs     ${cids.length}`);
  say(`  pinned          ${pinned}`);
  say(`  failed          ${failed}`);
  say(`  bytes pinned    ${humanBytes(bytes)} (${bytes.toLocaleString()} bytes)`);

  printBoundaries(totalUnpinnable, opts);
  process.exitCode = failed > 0 || wallets.some((w) => w.error) ? 1 : 0;
}

function printBoundaries(unpinnable, opts) {
  say();
  say("What this does not cover");
  if (unpinnable) {
    const it = unpinnable === 1 ? "it" : "them";
    say(
      `  ${unpinnable} matched ${plural(unpinnable, "work has", "works have")} no published ` +
        "content address yet — there is nothing"
    );
    say(
      `  to pin for ${it} until addresses are published. ` +
        `${unpinnable === 1 ? "It is" : "They are"} listed above, not dropped.`
    );
  }
  say("  Bitmark-era works cannot be enumerated from a wallet address at all.");
  say(`  Look those up by token ID on ${opts.statusUrl}.`);
}

main().catch((e) => {
  progressDone();
  if (e instanceof CliError) {
    console.error("feralfile-keep: " + e.message);
    process.exitCode = 2;
    return;
  }
  console.error("feralfile-keep: " + (e && e.stack ? e.stack : e));
  process.exitCode = 1;
});
