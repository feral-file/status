#!/usr/bin/env node
// feralfile-keep — give it your wallet address, get your own copies of the art
// it holds, pinned on your own IPFS node.
//
// One shape, one pipeline. Every input is a *resolver* that turns its source
// into DP-1-shaped item records: the published Feral File census, a token's
// own metadata, an assets manifest captured off a device. Everything after
// that — classify, collect, pin, report, write the kept record — reads only
// those records and never knows which resolver made them. The pinner has no
// idea what a census is. See ARCHITECTURE.md.
//
// Default scope is every blockchain-native artwork the wallet holds, on any
// platform we can enumerate. Feral File's published works are the best-
// evidenced tier of that, not the whole of it: for those the census at
// status.feralfile.com says exactly which files make the work, so the pin is
// probed and file-complete. For everything else the token's own metadata is
// the evidence, and the report says so tier by tier.
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

import { writeFileSync, readFileSync } from "node:fs";
import { basename } from "node:path";
import { randomUUID } from "node:crypto";

const BLOCKSCOUT = "https://eth.blockscout.com/api/v2";
const TZKT = "https://api.tzkt.io/v1";
const PAGE_CAP = 400; // indexer pages; 400 x 1000 rows is plenty
const TZKT_LIMIT = 1000;
const DEFAULT_STATUS_URL = "https://status.feralfile.com";
const DEFAULT_API = "http://127.0.0.1:5001";
const DEFAULT_RECORD = "keep-record.json";
const SHARD_CONCURRENCY = 8;
const RESOLVE_CONCURRENCY = 8;
const STALL_TIMEOUT_SEC = 120; // a pin is failed this long after the last data arrived
const LIST_PREVIEW = 20; // lines printed per tier before "… and N more"
const LABEL_MAX = 60;

// ------------------------------------------------------------- record model
//
// The one internal shape. A resolver produces these; nothing downstream reads
// anything else.
//
//   {
//     id,          stable item identity
//     title,       human name
//     source?,     the URL the work is played from, when one is known
//     collection?, the published grouping it came from (census exhibition)
//     provenance:  { chain: "evm"|"tezos", contract, tokenId }
//     evidence:    "observed" | "declared-complete" | "declared-partial" | "none"
//     assets:      [ { url?, cid?, path?, sha256?, contentType?, bytes?,
//                      status?, field?, wholeSeries?, resolvedCid? } ]
//     boundary?:   "<name>: <detail>" — present exactly when evidence is "none"
//   }
//
// An asset with a cid can be pinned. An asset with a cid *and* a path names one
// file inside a shared directory and has to be resolved by the node before it
// can be pinned; the resolved address lands on `resolvedCid`. An asset with a
// url and no cid is a reference that cannot be kept — it is carried so the
// report can name the domains a collection is leaning on.

const EV = {
  OBSERVED: "observed",
  COMPLETE: "declared-complete",
  PARTIAL: "declared-partial",
  NONE: "none",
};

// Tiers, in report order. The order is the evidence order: how much the tool
// can honestly claim about what a pin preserves.
const OBSERVED_TIER = {
  key: "observed",
  title: "observed",
  blurb: "captured while the work ran — the file list is what it actually fetched",
};

const TIERS = [
  {
    key: "verified",
    title: "verified",
    blurb: "census-listed files — probed, file-complete",
  },
  {
    key: "content-addressed",
    title: "content-addressed",
    blurb: "metadata declares IPFS references — pinning what it declares",
  },
  {
    key: "on-chain",
    title: "on-chain",
    blurb: "media lives in the token itself — nothing to pin, survives with the chain",
  },
  {
    key: "mutable-only",
    title: "mutable-only",
    blurb: "every media reference is a plain https URL — can be bookmarked, not kept",
  },
  {
    key: "unresolved",
    title: "unresolved",
    blurb: "no usable metadata — nothing to go on",
  },
];

const ALL_TIERS = [OBSERVED_TIER, ...TIERS];

function boundary(name, detail) {
  return `${name}: ${detail}`;
}

function boundaryName(s) {
  const i = s.indexOf(": ");
  return i < 0 ? s : s.slice(0, i);
}

function boundaryDetail(s) {
  const i = s.indexOf(": ");
  return i < 0 ? "" : s.slice(i + 2);
}

// The single place evidence becomes a report tier.
function tierOf(rec) {
  if (rec.evidence === EV.OBSERVED) return OBSERVED_TIER.key;
  if (rec.evidence === EV.COMPLETE) return "verified";
  if (rec.evidence === EV.PARTIAL) return "content-addressed";
  return boundaryName(rec.boundary || "unresolved: no evidence");
}

function provKey(rec) {
  return rec.provenance.contract + "/" + rec.provenance.tokenId;
}

function pinnableAssets(rec) {
  return rec.assets.filter((a) => a.cid);
}

function referenceHosts(rec) {
  const hosts = new Set();
  for (const a of rec.assets) {
    if (a.cid || !a.url) continue;
    const h = refHost(a.url);
    if (h) hosts.add(h);
  }
  return hosts;
}

function itemId(chain, contract, tokenId) {
  const ns = chain === "evm" ? "eip155:1" : "tezos:mainnet";
  return `${ns}:${contract}:${tokenId}`;
}

function clip(s, n = LABEL_MAX) {
  return s.length > n ? s.slice(0, n - 3) + "…" : s;
}

const USAGE = `feralfile-keep <address...> [options]

Pins the blockchain-native art held by the given wallet address(es) to your
local IPFS node — every platform this can enumerate, not just Feral File.

Addresses
  0x…            Ethereum (40 hex characters)
  name.eth       ENS name, resolved via Blockscout
  name.tez       Tezos domain, resolved via TzKT
  tz1/tz2/tz3…   Tezos

Options
  --manifest <file|url>  an assets manifest from capture-export (repeatable)
  --dry-run            enumerate and report, pin nothing
  --ff-only            old scope: published Feral File works only
  --limit <n>          trial run — keep at most n works per tier
  --verbose            print every work line instead of the first ${LIST_PREVIEW}
  --api <url>          kubo HTTP API (default ${DEFAULT_API})
  --timeout <seconds>  absolute per-pin timeout handed to the node; without it a
                       pin runs as long as data keeps arriving and is failed
                       after ${STALL_TIMEOUT_SEC}s of silence
  --out <file>         also write the unique CID list, one per line
  --record <file>      where to write the kept record (default ${DEFAULT_RECORD})
  --status-url <url>   published data source (default ${DEFAULT_STATUS_URL})
  -h, --help           this text

Tiers
  Every held token lands in one, and all of them are reported:
${TIERS.map((t) => `    ${t.title.padEnd(18)} ${t.blurb}`).join("\n")}
  A --manifest adds one more, above all of them:
    ${OBSERVED_TIER.title.padEnd(18)} ${OBSERVED_TIER.blurb}

Boundaries
  The content-addressed tier keeps what the metadata declares. A code-based
  work's undeclared dependencies are not captured.
  Bitmark-era works cannot be enumerated from a wallet address. Look those
  up by token ID on ${DEFAULT_STATUS_URL} instead.
`;

// ---------------------------------------------------------------- arguments

function parseArgs(argv) {
  const opts = {
    addresses: [],
    manifests: [],
    dryRun: false,
    ffOnly: false,
    verbose: false,
    limit: null,
    api: DEFAULT_API,
    statusUrl: DEFAULT_STATUS_URL,
    timeout: null,
    out: null,
    record: DEFAULT_RECORD,
    help: false,
  };
  const needsValue = new Set([
    "--api",
    "--timeout",
    "--out",
    "--status-url",
    "--limit",
    "--manifest",
    "--record",
  ]);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "-h" || a === "--help") {
      opts.help = true;
    } else if (a === "--dry-run") {
      opts.dryRun = true;
    } else if (a === "--ff-only") {
      opts.ffOnly = true;
    } else if (a === "--verbose") {
      opts.verbose = true;
    } else if (needsValue.has(a)) {
      const v = argv[++i];
      if (v === undefined) fail(`${a} needs a value.`);
      if (a === "--api") opts.api = v.replace(/\/+$/, "");
      else if (a === "--status-url") opts.statusUrl = v.replace(/\/+$/, "");
      else if (a === "--out") opts.out = v;
      else if (a === "--record") opts.record = v;
      else if (a === "--manifest") opts.manifests.push(v);
      else if (a === "--timeout") {
        const n = Number(v);
        if (!Number.isFinite(n) || n <= 0) fail(`--timeout wants a positive number of seconds, got "${v}".`);
        opts.timeout = n;
      } else if (a === "--limit") {
        const n = Number(v);
        if (!Number.isInteger(n) || n <= 0) fail(`--limit wants a positive whole number, got "${v}".`);
        opts.limit = n;
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

// Name resolution: *.eth via Blockscout search, *.tez via TzKT domains.
// Both keyless — the same services the enumeration already trusts.
async function resolveName(name) {
  const lower = name.toLowerCase();
  if (lower.endsWith(".eth")) {
    const r = await fetch(`${BLOCKSCOUT}/search?q=${encodeURIComponent(lower)}`);
    if (!r.ok) fail(`Blockscout answered HTTP ${r.status} resolving "${name}".`);
    const d = await r.json();
    for (const it of d.items || []) {
      const ens = it.ens_info && it.ens_info.name;
      const addr = it.address_hash || it.address;
      if (it.type === "ens_domain" && ens === lower && addr) {
        return { address: addr, kind: "eth" };
      }
    }
    fail(`"${name}" did not resolve to an Ethereum address on Blockscout.`);
  }
  if (lower.endsWith(".tez")) {
    const r = await fetch(
      `${TZKT}/domains?name=${encodeURIComponent(lower)}&select=name,address`
    );
    if (!r.ok) fail(`TzKT answered HTTP ${r.status} resolving "${name}".`);
    const rows = await r.json();
    const hit = rows.find((row) => row.name === lower && row.address);
    if (hit) {
      const addr = hit.address.address || hit.address;
      if (typeof addr === "string") return { address: addr, kind: "tezos" };
    }
    fail(`"${name}" did not resolve to a Tezos address on TzKT.`);
  }
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
//
// Both indexers hand back the token's metadata on the same rows that carry the
// balances, so the wider scope costs no extra API calls — only a bigger page.

async function fetchEthHoldings(addr, wantMetadata) {
  const held = [];
  let extra = "";
  for (let page = 0; page < PAGE_CAP; page++) {
    const { data, notFound } = await getJson(
      `${BLOCKSCOUT}/addresses/${addr}/nft?type=ERC-721%2CERC-1155${extra}`
    );
    if (notFound) return held; // address never seen on chain
    for (const it of data.items || []) {
      if (it.id && it.token && it.token.address_hash) {
        held.push({
          contract: it.token.address_hash,
          tokenId: String(it.id),
          metadata: wantMetadata ? it.metadata ?? null : null,
        });
      }
    }
    progress(`reading Ethereum holdings from Blockscout — ${held.length} tokens…`);
    if (!data.next_page_params) return held;
    extra = "&" + new URLSearchParams(data.next_page_params).toString();
  }
  return held;
}

async function fetchTezosHoldings(addr, wantMetadata) {
  const held = [];
  const select = wantMetadata
    ? "token.contract.address,token.tokenId,token.metadata"
    : "token.contract.address,token.tokenId";
  for (let page = 0; page < PAGE_CAP; page++) {
    const { data: rows } = await getJson(
      `${TZKT}/tokens/balances?account=${addr}&balance.gt=0&limit=${TZKT_LIMIT}` +
        `&offset=${page * TZKT_LIMIT}&select=${select}`
    );
    for (const row of rows) {
      const contract = row["token.contract.address"];
      const tokenId = row["token.tokenId"];
      if (contract && tokenId != null) {
        held.push({
          contract,
          tokenId: String(tokenId),
          metadata: wantMetadata ? row["token.metadata"] ?? null : null,
        });
      }
    }
    progress(`reading Tezos holdings from TzKT — ${held.length} token balances…`);
    if (rows.length < TZKT_LIMIT) return held;
  }
  return held;
}

function tokenKey(h) {
  return h.contract + "/" + h.tokenId;
}

function dedupeHeld(held) {
  const seen = new Map();
  for (const h of held) {
    const k = tokenKey(h);
    const prev = seen.get(k);
    if (!prev) seen.set(k, h);
    else if (!prev.metadata && h.metadata) seen.set(k, h);
  }
  return [...seen.values()];
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

// ----------------------------------------------------- resolver: the census
//
// Join held (contract, tokenId) pairs against the published shards. One record
// per matched work entry — the same join static/wallet.js runs. The census
// publishes the whole file list for a work, so its evidence is
// declared-complete: not "somebody looked", but "the publisher says this is all
// of it".

async function resolveCensus(unique, kind, census) {
  const index = await census.index();
  const candidates = unique.filter((h) => index[h.tokenId]);
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

  const chain = kind === "eth" ? "evm" : "tezos";
  const records = [];
  const matchedKeys = new Set();
  for (const h of candidates) {
    for (const exId of index[h.tokenId]) {
      const shard = shards.get(exId);
      for (const entry of (shard && shard.works[h.tokenId]) || []) {
        if (!sameContract(kind, entry.contract || "", h.contract)) continue;
        matchedKeys.add(tokenKey(h));
        const assets = [];
        for (const f of entry.files || []) {
          if (f.cid && (f.host === "ipfs" || f.host === "ipfs-archival")) {
            assets.push({
              cid: f.cid,
              field: f.res || undefined,
              wholeSeries: f.host === "ipfs-archival",
            });
          }
        }
        records.push({
          id: itemId(chain, entry.contract || h.contract, h.tokenId),
          // The census may have no name for an entry while the token's own
          // metadata does — use the best name in hand before the bare number.
          title: entry.name || metadataName(h.metadata) || "token …" + h.tokenId.slice(-8),
          collection: shard.exhibition.title || shard.exhibition.slug || "exhibition",
          provenance: { chain, contract: entry.contract || h.contract, tokenId: h.tokenId },
          evidence: EV.COMPLETE,
          assets,
        });
      }
    }
  }
  return { records, matchedKeys };
}

// --------------------------------------------------- resolver: token metadata

// The fields a token's metadata may point its media at. TZIP-21 (Tezos) and
// the ERC-721/1155 conventions (Ethereum) overlap but spell things
// differently, so both spellings are checked.
const MEDIA_FIELDS = [
  "image",
  "image_url",
  "animation_url",
  "artifact_uri",
  "artifactUri",
  "display_uri",
  "displayUri",
  "thumbnail_uri",
  "thumbnailUri",
];

// Pull every media reference out of a metadata object, keeping the field name
// so the report can say what decided a token's tier.
function metadataRefs(metadata) {
  const refs = [];
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) return refs;
  for (const f of MEDIA_FIELDS) {
    if (typeof metadata[f] === "string" && metadata[f].trim()) {
      refs.push({ field: f, value: metadata[f].trim() });
    }
  }
  if (Array.isArray(metadata.formats)) {
    for (const fo of metadata.formats) {
      if (fo && typeof fo.uri === "string" && fo.uri.trim()) {
        refs.push({ field: "formats[].uri", value: fo.uri.trim() });
      }
    }
  }
  return refs;
}

// A CID we are willing to hand to a node. Deliberately narrow: a wrong pin is
// worse than a missed one, because it looks like success.
function isValidCid(s) {
  if (!s) return false;
  if (/^Qm[1-9A-HJ-NP-Za-km-z]{44}$/.test(s)) return true; // CIDv0, base58btc
  if (/^ba[a-z2-7]{44,}$/.test(s)) return true; // CIDv1, lowercase base32
  return false;
}

// Recognize a content address in a reference, whether it arrives as an
// ipfs:// URI or as some gateway's /ipfs/<cid> URL. Returns null for anything
// that is not content-addressed — including gateway-shaped URLs whose "CID"
// does not validate.
function cidFromRef(value) {
  let rest = null;
  const m = /^ipfs:\/{0,2}(.+)$/i.exec(value);
  if (m) {
    rest = m[1];
  } else if (/^https?:\/\//i.test(value)) {
    const g = /\/ipfs\/(.+)$/i.exec(value);
    if (!g) return null;
    rest = g[1];
  } else {
    return null;
  }
  rest = rest.split(/[?#]/)[0];
  const parts = rest.split("/").filter(Boolean);
  if (!parts.length) return null;
  const cid = parts[0];
  if (!isValidCid(cid)) return null;
  const path = parts.slice(1).join("/");
  return { cid, path };
}

function refHost(value) {
  try {
    return new URL(value).host;
  } catch {
    return null;
  }
}

function metadataName(metadata) {
  if (metadata && typeof metadata === "object" && typeof metadata.name === "string" && metadata.name.trim()) {
    return metadata.name.trim();
  }
  return null;
}

// Turn one held token into a record from its metadata alone. Everything lands
// somewhere; nothing is dropped for being inconvenient. Metadata is a partial
// declaration by construction — it names the media the token points at, never
// the dependencies that media reaches for — so a resolvable token is
// declared-partial, not complete.
function metadataRecord(h, kind) {
  const chain = kind === "eth" ? "evm" : "tezos";
  const md = h.metadata;
  const base = {
    id: itemId(chain, h.contract, h.tokenId),
    title: metadataName(md) || "token …" + h.tokenId.slice(-8),
    provenance: { chain, contract: h.contract, tokenId: h.tokenId },
  };

  if (!md || typeof md !== "object" || Array.isArray(md)) {
    return { ...base, evidence: EV.NONE, assets: [], boundary: boundary("unresolved", "no metadata from the indexer") };
  }
  const refs = metadataRefs(md);
  if (!refs.length) {
    return {
      ...base,
      evidence: EV.NONE,
      assets: [],
      boundary: boundary("unresolved", "metadata present, no media reference in it"),
    };
  }

  const assets = [];
  const seenCid = new Set();
  let sawData = false;
  let sawHttp = false;
  let decidedBy = null;
  let anyCid = false;

  for (const r of refs) {
    const found = cidFromRef(r.value);
    if (found) {
      const k = found.cid + "/" + found.path;
      if (!seenCid.has(k)) {
        seenCid.add(k);
        assets.push({ cid: found.cid, path: found.path || undefined, field: r.field });
        anyCid = true;
      }
      if (!decidedBy) decidedBy = r.field;
    } else if (/^data:/i.test(r.value)) {
      // Inline media. It is already kept by whoever keeps the chain, and
      // copying the bytes into a record would only bloat it, so the boundary
      // names it instead.
      sawData = true;
      if (!decidedBy) decidedBy = r.field;
    } else if (/^https?:\/\//i.test(r.value)) {
      sawHttp = true;
      assets.push({ url: r.value, field: r.field });
    }
  }

  if (anyCid) {
    return { ...base, evidence: EV.PARTIAL, assets, boundary: undefined };
  }
  if (sawData) {
    return { ...base, evidence: EV.NONE, assets, boundary: boundary("on-chain", `${decidedBy} → data: URI`) };
  }
  if (sawHttp) {
    const hosts = [...new Set(assets.map((a) => refHost(a.url)).filter(Boolean))];
    return {
      ...base,
      evidence: EV.NONE,
      assets,
      boundary: boundary("mutable-only", `https only (${hosts.join(", ") || "unparseable host"})`),
    };
  }
  return {
    ...base,
    evidence: EV.NONE,
    assets,
    boundary: boundary("unresolved", `media reference in an unrecognized form (${refs[0].field})`),
  };
}

function resolveMetadata(unique, kind, skipKeys) {
  const records = [];
  let n = 0;
  for (const h of unique) {
    if (skipKeys.has(tokenKey(h))) continue;
    if (++n % 2000 === 0) progress(`sorting ${n.toLocaleString()} remaining tokens by evidence…`);
    records.push(metadataRecord(h, kind));
  }
  progressDone();
  return records;
}

// ------------------------------------------------ resolver: assets manifests
//
// The only input that can say "observed". An assets manifest is written by
// capture-export from a feral-controld offlinecache store: the file list a
// device actually fetched while the work ran, each blob hashed and already
// content-addressed. Nothing here is inferred from a declaration — it is a
// recording. The manifest schema is a PROPOSED DP-1 extension and belongs in
// display-protocol/dp1; this only reads it.

async function readManifest(src) {
  if (/^https?:\/\//i.test(src)) {
    const r = await fetch(src, { headers: { accept: "application/json" } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  }
  return JSON.parse(readFileSync(src, "utf8"));
}

function manifestRecord(m, src) {
  if (!m || typeof m !== "object" || Array.isArray(m)) throw new Error("not a JSON object");
  if (!Array.isArray(m.assets)) throw new Error("no assets array — is this an assets manifest?");
  const item = m.item && typeof m.item === "object" ? m.item : {};
  const id = m.itemId || item.id || basename(String(src)).replace(/\.assets\.json$/i, "");
  const c = (item.provenance && item.provenance.contract) || {};
  const assets = m.assets.map((a) => ({
    url: a.url,
    cid: a.cid,
    sha256: a.sha256,
    contentType: a.contentType,
    bytes: a.bytes,
    status: a.status,
  }));
  return {
    id: String(id),
    title: item.title || String(id),
    source: typeof item.source === "string" ? item.source : undefined,
    provenance: {
      chain: c.chain || "other",
      contract: c.address || "",
      tokenId: c.tokenId == null ? "" : String(c.tokenId),
    },
    evidence: EV.OBSERVED,
    assets,
  };
}

// Two exports of the same capture are the same item, whatever the files are
// called. Merge them rather than double-counting: same id, union of assets.
async function resolveManifests(sources) {
  const byId = new Map();
  let read = 0;
  const problems = [];
  for (const src of sources) {
    let m;
    try {
      m = await readManifest(src);
    } catch (e) {
      problems.push(`${src} — could not be read (${e.message})`);
      continue;
    }
    let rec;
    try {
      rec = manifestRecord(m, src);
    } catch (e) {
      problems.push(`${src} — ${e.message}`);
      continue;
    }
    read++;
    const prev = byId.get(rec.id);
    if (!prev) {
      byId.set(rec.id, rec);
      continue;
    }
    const seen = new Set(prev.assets.map((a) => a.cid || a.url));
    for (const a of rec.assets) {
      const k = a.cid || a.url;
      if (!seen.has(k)) {
        seen.add(k);
        prev.assets.push(a);
      }
    }
    if (!prev.source && rec.source) prev.source = rec.source;
  }
  return { records: [...byId.values()], read, problems };
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

// Pinning is the one call that can legitimately run for many minutes, and it
// is the one call that must not be cut short while it is actually working.
// `progress=true` is what makes that possible: kubo sends response headers at
// once and streams a progress line per block fetched, so the runtime's own
// 5-minute headers timeout never fires — and those same lines are the
// liveness signal. Without an explicit --timeout, the clock re-arms on every
// progress line: a dead CID nobody serves is failed after STALL_TIMEOUT_SEC
// of silence, while a huge cold pin can run for hours as long as data keeps
// arriving. With --timeout the node enforces an absolute limit and the client
// gets a little more rope, so a node-side timeout reports as a timeout rather
// than as a torn connection.
async function pinCid(api, cid, timeoutSec, onProgress) {
  const t = timeoutSec ? `&timeout=${timeoutSec}s` : "";
  const ac = new AbortController();
  let timer;
  let stalled = false;
  const arm = (ms, isStall) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      stalled = isStall;
      ac.abort();
    }, ms);
  };
  if (timeoutSec) arm(timeoutSec * 1000 + 15000, false);
  else arm(STALL_TIMEOUT_SEC * 1000, true);
  try {
    const r = await fetch(
      api + `/api/v0/pin/add?arg=${encodeURIComponent(cid)}&recursive=true&progress=true${t}`,
      { method: "POST", signal: ac.signal }
    );
    if (!r.ok) {
      let msg = `HTTP ${r.status}`;
      try {
        const j = JSON.parse(await r.text());
        if (j.Message) msg = j.Message;
      } catch {}
      throw new Error(msg);
    }
    let pinned = false;
    for await (const line of ndjson(r.body)) {
      if (line.Type === "error" || line.Message) throw new Error(line.Message || "pin failed");
      if (Number.isFinite(line.Progress)) {
        if (!timeoutSec) arm(STALL_TIMEOUT_SEC * 1000, true);
        if (onProgress) onProgress(line.Progress);
      }
      if (Array.isArray(line.Pins)) pinned = true;
    }
    if (!pinned) throw new Error("the node closed the connection before the pin finished");
  } catch (e) {
    if (stalled) throw new Error(`no data from the network for ${STALL_TIMEOUT_SEC}s — gave up`);
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

// kubo streams newline-delimited JSON; anything unparseable is a keep-alive
// artifact, not a message, so it is skipped rather than thrown on.
async function* ndjson(body) {
  const reader = body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (value) buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (line) {
        let j;
        try {
          j = JSON.parse(line);
        } catch {
          continue;
        }
        yield j;
      }
    }
    if (done) break;
  }
  const tail = buf.trim();
  if (tail) {
    try {
      yield JSON.parse(tail);
    } catch {}
  }
}

// StorageMax is kubo's own ceiling, and a default install's 10 GB is smaller
// than plenty of single collections. Say so before the run instead of letting
// pins fail into it.
async function repoStat(api) {
  try {
    const j = await ipfsPost(api, "/api/v0/repo/stat?size-only=true", { deadlineMs: 15000 });
    const size = Number(j.RepoSize);
    const max = Number(j.StorageMax);
    return Number.isFinite(size) && Number.isFinite(max) && max > 0 ? { size, max } : null;
  } catch {
    return null; // the check is a courtesy, never a failure
  }
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

// A reference of the form <cid>/<path> names one file inside a directory that
// often holds thousands of other people's tokens. Pinning the root would be a
// lie about what you kept and a bill you did not agree to, so the path is
// resolved to its own CID first. Only the node can do that.
async function resolvePathCid(api, cid, path) {
  const arg = `/ipfs/${cid}/${path}`;
  const j = await ipfsPost(api, `/api/v0/resolve?arg=${encodeURIComponent(arg)}`, {
    deadlineMs: 60000,
  });
  const resolved = String(j.Path || "").replace(/^\/ipfs\//, "").split("/")[0];
  if (!isValidCid(resolved)) throw new Error("resolve returned no CID");
  return resolved;
}

function isTimeout(err) {
  const m = String((err && err.message) || err).toLowerCase();
  return m.includes("timeout") || m.includes("abort") || m.includes("deadline");
}

// -------------------------------------------------------------------- report

function tallyLine(totalHeld, counts) {
  const parts = TIERS.map((t) => `${t.title} ${(counts[t.key] || 0).toLocaleString()}`);
  return (
    `  ${totalHeld.toLocaleString()} ${plural(totalHeld, "token")} held → ` + parts.join(" · ")
  );
}

function printLines(lines, verbose, limited) {
  const shown = verbose ? lines.length : Math.min(lines.length, LIST_PREVIEW);
  for (let i = 0; i < shown; i++) say("      " + lines[i]);
  if (shown < lines.length) {
    say(`      … and ${(lines.length - shown).toLocaleString()} more (--verbose for all)`);
  }
  if (limited) say(`      (--limit in force — the rest of this tier was counted, not kept)`);
}

// One record, one report line. The only place a tier decides how a record
// reads; everything above it is the same shape.
function recordLine(rec, tier) {
  const cids = pinnableAssets(rec);
  if (tier === "verified") {
    let tail;
    if (cids.length) {
      const series = cids.filter((c) => c.wholeSeries).length;
      tail =
        `${cids.length} pinnable ${plural(cids.length, "file")}` +
        (series ? ` (${series} whole-series archival — large)` : "");
    } else {
      tail = "nothing to pin yet";
    }
    return `${rec.collection} — ${rec.title} — ${tail}`;
  }
  if (tier === OBSERVED_TIER.key) {
    return (
      `${clip(rec.title)} — ${rec.assets.length} ${plural(rec.assets.length, "asset")}` +
      ` (${cids.length} content-addressed)`
    );
  }
  if (tier === "content-addressed") {
    const fields = [...new Set(cids.map((x) => x.field))].join(", ");
    const paths = cids.filter((x) => x.path).length;
    return (
      `${clip(rec.title)} — ${cids.length} ${plural(cids.length, "reference")} (${fields})` +
      (paths ? ` — ${paths} inside a directory, needs resolution` : "")
    );
  }
  return `${clip(rec.title)} — ${boundaryDetail(rec.boundary)}`;
}

// ---------------------------------------------------------------- collecting
//
// Records in, pin work out. This stage is the whole reason for the record
// shape: it never asks where a record came from, only what evidence it carries
// and which of its assets have a content address.

function collectRecords(records, ctx, opts) {
  const counts = {};
  const lines = {};
  const limited = {};
  const mutableHosts = new Map();
  for (const t of ALL_TIERS) {
    counts[t.key] = 0;
    lines[t.key] = [];
    limited[t.key] = false;
  }

  for (const rec of records) {
    const tier = tierOf(rec);
    counts[tier] = (counts[tier] || 0) + 1;
    const cids = pinnableAssets(rec);
    if (rec.evidence === EV.COMPLETE && !cids.length) ctx.unpinnable++;
    if (tier === "mutable-only") {
      for (const h of referenceHosts(rec)) mutableHosts.set(h, (mutableHosts.get(h) || 0) + 1);
    }
    if (opts.limit && lines[tier].length >= opts.limit) {
      limited[tier] = true;
      continue;
    }
    lines[tier].push(recordLine(rec, tier));
    ctx.kept.push(rec);
    for (const a of cids) {
      if (a.path) {
        const k = a.cid + "/" + a.path;
        const p = ctx.pending.get(k) || { cid: a.cid, path: a.path, works: new Set(), assets: [] };
        p.works.add(rec.title);
        p.assets.push(a);
        ctx.pending.set(k, p);
      } else {
        const r = ctx.cidMap.get(a.cid) || { wholeSeries: false, works: new Set() };
        r.wholeSeries = r.wholeSeries || Boolean(a.wholeSeries);
        r.works.add(rec.title);
        ctx.cidMap.set(a.cid, r);
      }
    }
  }

  // The verified tier counts tokens, not census entries: one token published in
  // two exhibitions is one thing you hold, matched twice.
  counts.verified = new Set(
    records.filter((r) => r.evidence === EV.COMPLETE).map(provKey)
  ).size;

  return { counts, lines, limited, mutableHosts };
}

// ---------------------------------------------------------- the kept record
//
// v0 of "what you keep is itself a playable document". One DP-1 playlist, one
// item per work that actually has a pin on this disk, each carrying the
// evidence it was kept on and the content addresses that landed. No
// signatures: nothing here is a claim about anyone but the person who ran it.

function keepRecordDoc(records, pinnedCids, meta = {}) {
  const byId = new Map();
  for (const rec of records) {
    const assets = [];
    for (const a of rec.assets) {
      const cid = a.resolvedCid || a.cid;
      if (!cid || !pinnedCids.has(cid)) continue;
      assets.push({
        url: a.url,
        field: a.field,
        contentType: a.contentType,
        sha256: a.sha256,
        bytes: a.bytes,
        cid,
        ...(a.path ? { from: `${a.cid}/${a.path}` } : {}),
        ...(a.wholeSeries ? { wholeSeries: true } : {}),
      });
    }
    if (!assets.length) continue;
    const prev = byId.get(rec.id);
    if (prev) {
      const seen = new Set(prev.assets.map((a) => a.cid));
      for (const a of assets) {
        if (seen.has(a.cid)) continue;
        seen.add(a.cid);
        prev.assets.push(a);
      }
      continue;
    }
    byId.set(rec.id, {
      id: rec.id,
      title: rec.title,
      ...(rec.collection ? { collection: rec.collection } : {}),
      source: rec.source || `ipfs://${assets[0].cid}`,
      provenance: {
        type: "onChain",
        contract: {
          chain: rec.provenance.chain,
          address: rec.provenance.contract,
          tokenId: rec.provenance.tokenId,
        },
      },
      evidence: rec.evidence,
      assets,
    });
  }
  const items = [...byId.values()];
  for (const it of items) {
    // Drop the keys we could not honestly fill, rather than shipping nulls.
    for (const a of it.assets) for (const k of Object.keys(a)) if (a[k] === undefined) delete a[k];
    if (!it.provenance.contract.address) delete it.provenance;
  }
  return {
    dpVersion: "1.0.0",
    id: meta.id || randomUUID(),
    slug: "keep-record",
    title: "Kept — feralfile-keep",
    created: meta.created || new Date().toISOString(),
    assetsVersion: "0.0.1-draft",
    items,
  };
}

// ---------------------------------------------------------------------- main

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help || (opts.addresses.length === 0 && opts.manifests.length === 0)) {
    console.log(USAGE);
    process.exitCode = opts.help ? 0 : 2;
    return;
  }

  const wallets = [];
  for (const a of opts.addresses) {
    let kind = detectWallet(a);
    let address = a;
    if (!kind) {
      const resolved = await resolveName(a);
      if (resolved) {
        say(`${a} → ${resolved.address}`);
        ({ address, kind } = resolved);
      } else {
        fail(
          `"${a}" is not an address this understands.\n` +
            "  Ethereum looks like 0x followed by 40 hex characters, or a *.eth name.\n" +
            "  Tezos looks like tz1/tz2/tz3 followed by 33 base58 characters, or a *.tez name.\n" +
            "  A 64-character Bitmark token ID is not a wallet — look those up\n" +
            `  by token ID on ${opts.statusUrl}.`
        );
      }
    }
    wallets.push({ address, kind });
  }

  const census = makeCensus(opts.statusUrl);
  say(
    opts.ffOnly
      ? "feralfile-keep — your Feral File library, pinned where you can reach it."
      : "feralfile-keep — hold your own copies of the art you collect."
  );
  if (wallets.length) say(`Published data: ${opts.statusUrl}`);
  if (opts.ffOnly) say("Scope: --ff-only — published Feral File works only.");
  if (opts.limit) say(`Trial run: --limit ${opts.limit} work${opts.limit === 1 ? "" : "s"} per tier.`);

  // Everything the stages below share. cidMap is CID -> {wholeSeries, works};
  // pending holds <cid>/<path> refs only the node can turn into a CID; kept is
  // every record that actually contributed pin work.
  const ctx = { cidMap: new Map(), pending: new Map(), kept: [], unpinnable: 0 };
  let totalMatches = 0;
  const grandCounts = {};

  for (const w of wallets) {
    const chainName = w.kind === "eth" ? "Ethereum" : "Tezos";
    say();
    say(`Wallet ${w.address}  (${chainName})`);
    let held;
    try {
      held =
        w.kind === "eth"
          ? await fetchEthHoldings(w.address, !opts.ffOnly)
          : await fetchTezosHoldings(w.address, !opts.ffOnly);
    } catch (e) {
      progressDone();
      say(`  could not read holdings: ${e.message}`);
      say(`  (${w.kind === "eth" ? "Blockscout" : "TzKT"} may be briefly unavailable — try again.)`);
      w.error = true;
      continue;
    }

    const unique = dedupeHeld(held);

    // Resolver 1: the published census.
    let census1;
    try {
      census1 = await resolveCensus(unique, w.kind, census);
    } catch (e) {
      progressDone();
      say(`  could not load published data: ${e.message}`);
      w.error = true;
      continue;
    }
    progressDone();
    totalMatches += census1.records.length;

    // Resolver 2: whatever the tokens say about themselves. --ff-only stops
    // here — the census join alone, nothing else examined.
    const records = opts.ffOnly
      ? census1.records
      : census1.records.concat(resolveMetadata(unique, w.kind, census1.matchedKeys));

    const { counts, lines, limited, mutableHosts } = collectRecords(records, ctx, opts);
    for (const k of Object.keys(counts)) grandCounts[k] = (grandCounts[k] || 0) + counts[k];

    const heldTotal = unique.length;
    if (opts.ffOnly) {
      say(
        `  ${held.length.toLocaleString()} ${plural(held.length, "token")} held ` +
          `(${heldTotal.toLocaleString()} unique) · ` +
          `${census1.records.length} published Feral File ${plural(census1.records.length, "work")} matched`
      );
    } else {
      say(tallyLine(heldTotal, counts));
    }

    for (const t of opts.ffOnly ? TIERS.slice(0, 1) : TIERS) {
      const count = counts[t.key] || 0;
      if (!count) continue;
      say();
      say(`  ${t.title} — ${t.blurb} (${count.toLocaleString()})`);
      printLines(lines[t.key], opts.verbose, limited[t.key]);
      if (t.key === "mutable-only" && mutableHosts.size) {
        const top = [...mutableHosts]
          .sort((a, b) => b[1] - a[1])
          .slice(0, 8)
          .map(([h, n]) => `${h} (${n.toLocaleString()})`);
        say(`      domains: ${top.join(", ")}`);
      }
    }
    if (!heldTotal) say("  This address holds nothing this can see.");
    else if (opts.ffOnly && !census1.records.length)
      say("  No published Feral File works found for this address.");
  }

  // Resolver 3: assets manifests. Not a wallet, so it gets its own section
  // rather than a tally line — but the same records, into the same stages.
  let usedManifests = false;
  if (opts.manifests.length) {
    const { records, read, problems } = await resolveManifests(opts.manifests);
    say();
    say(
      `Manifests  (${read} of ${opts.manifests.length} read → ` +
        `${records.length} ${plural(records.length, "item")})`
    );
    for (const p of problems) say(`  skipped ${p}`);
    if (records.length) {
      usedManifests = true;
      const { counts, lines, limited } = collectRecords(records, ctx, opts);
      grandCounts[OBSERVED_TIER.key] =
        (grandCounts[OBSERVED_TIER.key] || 0) + counts[OBSERVED_TIER.key];
      say();
      say(
        `  ${OBSERVED_TIER.title} — ${OBSERVED_TIER.blurb} ` +
          `(${counts[OBSERVED_TIER.key].toLocaleString()})`
      );
      printLines(lines[OBSERVED_TIER.key], opts.verbose, limited[OBSERVED_TIER.key]);
    }
  }

  // ---- resolve directory paths, which needs the node, then pin.
  const wantPin = !opts.dryRun;
  let nodeUp = false;
  if (wantPin) {
    nodeUp = await apiReachable(opts.api);
  }

  const unresolvedPaths = [];
  if (ctx.pending.size) {
    if (wantPin && nodeUp) {
      const items = [...ctx.pending.values()];
      let done = 0;
      for (let i = 0; i < items.length; i += RESOLVE_CONCURRENCY) {
        const batch = items.slice(i, i + RESOLVE_CONCURRENCY);
        await Promise.all(
          batch.map(async (it) => {
            try {
              const cid = await resolvePathCid(opts.api, it.cid, it.path);
              const rec = ctx.cidMap.get(cid) || { wholeSeries: false, works: new Set() };
              for (const wname of it.works) rec.works.add(wname);
              ctx.cidMap.set(cid, rec);
              for (const a of it.assets) a.resolvedCid = cid;
            } catch (e) {
              unresolvedPaths.push({ ...it, why: isTimeout(e) ? "resolve timed out" : e.message });
            }
            done++;
            progress(`resolving ${done}/${items.length} directory paths through the node…`);
          })
        );
      }
      progressDone();
    } else {
      for (const it of ctx.pending.values()) {
        unresolvedPaths.push({ ...it, why: opts.dryRun ? "dry run — not resolved" : "no node to resolve with" });
      }
    }
  }

  const cids = [...ctx.cidMap.keys()];
  const boundaryOpts = { ...opts, wallets: wallets.length > 0, manifests: usedManifests };

  say();
  if (opts.out) {
    writeFileSync(opts.out, cids.length ? cids.join("\n") + "\n" : "");
    say(`Wrote ${cids.length} ${plural(cids.length, "CID")} to ${opts.out}`);
  }

  if (unresolvedPaths.length) {
    say(
      `${unresolvedPaths.length} ${plural(unresolvedPaths.length, "reference")} ` +
        `${plural(unresolvedPaths.length, "points", "point")} inside a shared directory and ${plural(unresolvedPaths.length, "was", "were")} not pinned:`
    );
    for (const it of unresolvedPaths.slice(0, opts.verbose ? unresolvedPaths.length : LIST_PREVIEW)) {
      say(`  ${it.cid}/${it.path}  (${it.why})`);
    }
    if (!opts.verbose && unresolvedPaths.length > LIST_PREVIEW) {
      say(`  … and ${unresolvedPaths.length - LIST_PREVIEW} more (--verbose for all)`);
    }
    say("  Pinning the directory root instead would pull in every other token in it, so it is not done.");
    say();
  }

  if (!cids.length) {
    say("Nothing to pin.");
    printBoundaries(ctx.unpinnable, grandCounts, boundaryOpts);
    process.exitCode = wallets.some((w) => w.error) ? 1 : 0;
    return;
  }

  const seriesCount = [...ctx.cidMap.values()].filter((r) => r.wholeSeries).length;
  say(
    `${cids.length} unique content ${plural(cids.length, "address", "addresses")} to pin` +
      (seriesCount ? ` (${seriesCount} whole-series archival — large)` : "") +
      " — editions of the same work share files."
  );

  if (opts.dryRun) {
    say();
    say("Dry run — nothing was pinned. These would be:");
    for (const cid of cids) {
      const rec = ctx.cidMap.get(cid);
      say(`  ${cid}${rec.wholeSeries ? "  (whole-series archival — large)" : ""}`);
    }
    printBoundaries(ctx.unpinnable, grandCounts, boundaryOpts);
    process.exitCode = wallets.some((w) => w.error) ? 1 : 0;
    return;
  }

  // Pin phase.
  say();
  if (!nodeUp) {
    const file = opts.out || "feralfile-pins.txt";
    writeFileSync(file, cids.join("\n") + "\n");
    say(`No IPFS node answering at ${opts.api}.`);
    say(`Wrote the pin list to ${file} instead. When your node is running:`);
    say();
    say(`  xargs -n1 ipfs pin add < ${file}`);
    say();
    say("(Start a node with `ipfs daemon`, or point this at another one with --api.");
    say(' If the daemon itself dies with "address already in use", another program holds');
    say(" one of its ports — change Addresses.Gateway, commonly 8080, in the IPFS config.)");
    printBoundaries(ctx.unpinnable, grandCounts, boundaryOpts);
    return;
  }

  const stat = await repoStat(opts.api);
  if (stat && stat.size >= stat.max * 0.8) {
    const state = stat.size >= stat.max ? "already past" : "close to";
    say(`Note: the node's datastore is ${humanBytes(stat.size)}, ${state} its ${humanBytes(stat.max)} StorageMax ceiling.`);
    say("  Raise Datastore.StorageMax in the IPFS config before a large run, or pins may start failing.");
    say();
  }

  say(`Pinning ${cids.length} unique ${plural(cids.length, "CID")} to ${opts.api}` +
    (opts.timeout
      ? ` (${opts.timeout}s per pin)`
      : ` (a pin is failed after ${STALL_TIMEOUT_SEC}s with no data)`) + "…");
  say();

  // The record is rewritten after every successful pin, so an interrupted run
  // still says exactly what landed.
  const pinnedCids = new Set();
  const recordMeta = { id: randomUUID(), created: new Date().toISOString() };
  const writeRecord = () => {
    const doc = keepRecordDoc(ctx.kept, pinnedCids, recordMeta);
    writeFileSync(opts.record, JSON.stringify(doc, null, 2) + "\n");
    return doc;
  };
  let pinned = 0;
  let failed = 0;
  let bytes = 0;
  let n = 0;
  for (const cid of cids) {
    n++;
    const rec = ctx.cidMap.get(cid);
    const label = `[${n}/${cids.length}] pinning ${shortCid(cid)}`;
    progress(label + "…");
    const started = Date.now();
    try {
      await pinCid(opts.api, cid, opts.timeout, (blocks) => {
        const secs = ((Date.now() - started) / 1000).toFixed(0);
        progress(`${label} — ${blocks.toLocaleString()} ${plural(blocks, "block")}, ${secs}s…`);
      });
      const size = await cidSize(opts.api, cid);
      if (size != null) bytes += size;
      pinned++;
      pinnedCids.add(cid);
      writeRecord();
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

  // What actually landed, written as something a player can read back.
  const doc = writeRecord();

  say();
  say("Summary");
  say(`  works matched   ${totalMatches}`);
  say(`  unique CIDs     ${cids.length}`);
  say(`  pinned          ${pinned}`);
  say(`  failed          ${failed}`);
  say(`  bytes pinned    ${humanBytes(bytes)} (${bytes.toLocaleString()} bytes)`);
  say(`  kept record     ${opts.record} (${doc.items.length} ${plural(doc.items.length, "item")})`);

  printBoundaries(ctx.unpinnable, grandCounts, boundaryOpts);
  process.exitCode = failed > 0 || wallets.some((w) => w.error) ? 1 : 0;
}

function printBoundaries(unpinnable, counts, opts) {
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
  // These two hold on every wallet run, whatever it turned up.
  if (opts.wallets) {
    say("  The content-addressed tier keeps what the metadata declares. A code-based work's");
    say("  undeclared dependencies — a library it fetches at run time, a font, an API — are not");
    say("  captured by pinning what the metadata names.");
    say("  Bitmark-era works cannot be enumerated from a wallet address at all.");
    say(`  Look those up by token ID on ${opts.statusUrl}.`);
  }
  if (opts.manifests) {
    say("  An observed capture is one run of the work. A work that fetches something new");
    say("  on a later run has files no earlier capture holds.");
  }
  if (counts && counts["mutable-only"]) {
    say(
      `  ${counts["mutable-only"].toLocaleString()} mutable-only ${plural(counts["mutable-only"], "token")} ` +
        "can be bookmarked, not kept — whoever runs"
    );
    say("  those domains can change or withdraw the files at any time.");
  }
  if (opts.ffOnly) say("  --ff-only was in force: nothing outside the Feral File census was examined.");
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
