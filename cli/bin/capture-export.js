#!/usr/bin/env node
// capture-export — turn a feral-controld offlinecache capture record into a
// content-addressed asset manifest, and add its blobs to IPFS.
//
// PROTOTYPE. The input contract is the offlinecache store exactly as the
// device writes it (items/<itemId>.json + blobs/<sha256>); this tool reads
// that store as-is and never modifies it. The output is a PROPOSED DP-1
// extension — an "assets manifest": the fetchable, per-item file list that
// the spec does not define yet (ref manifest v0.1.0 is metadata/controls
// only; repro.assetsSHA256 is a verification hash list, not fetchable).
// Schema questions belong in display-protocol/dp1, not here.
//
// Usage:
//   capture-export <store-dir> [--api http://127.0.0.1:5001] [--out dir]
//
// <store-dir> holds items/ and blobs/ (copied from the device is fine).
// For every complete capture record found, this:
//   1. verifies each blob's sha256 against its filename,
//   2. adds each blob to IPFS (CIDv1) via the local kubo API,
//   3. writes <out>/<itemId>.assets.json mapping url -> {sha256, cid},
//   4. adds the manifest itself to IPFS and prints its CID.
// Incomplete captures (coverage.complete == false) are reported and
// skipped — an incomplete manifest presented as complete would be worse
// than none.

import { readFile, readdir, writeFile, mkdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";
import process from "node:process";

const args = process.argv.slice(2);
let storeDir = null;
let api = "http://127.0.0.1:5001";
let outDir = null;
for (let i = 0; i < args.length; i++) {
  if (args[i] === "--api") api = args[++i];
  else if (args[i] === "--out") outDir = args[++i];
  else if (!storeDir) storeDir = args[i];
}
if (!storeDir) {
  console.error("usage: capture-export <store-dir> [--api url] [--out dir]");
  process.exit(2);
}
outDir = outDir || path.join(storeDir, "exports");

async function ipfsAdd(bytes, name) {
  const form = new FormData();
  form.append("file", new Blob([bytes]), name);
  const r = await fetch(
    `${api}/api/v0/add?cid-version=1&raw-leaves=true&pin=true&quieter=true`,
    { method: "POST", body: form }
  );
  if (!r.ok) throw new Error(`ipfs add: HTTP ${r.status} ${await r.text()}`);
  const out = JSON.parse((await r.text()).trim().split("\n").pop());
  return out.Hash;
}

const itemsDir = path.join(storeDir, "items");
const blobsDir = path.join(storeDir, "blobs");
const records = (await readdir(itemsDir)).filter((f) => f.endsWith(".json"));
if (!records.length) {
  console.error(`no capture records in ${itemsDir}`);
  process.exit(1);
}
await mkdir(outDir, { recursive: true });

for (const f of records) {
  const rec = JSON.parse(await readFile(path.join(itemsDir, f), "utf8"));
  // Shipped 2.0.3 records carry no top-level itemId (the in-review branch's
  // ItemRecord does) — fall back to the DP-1 item id, then the filename.
  const itemId = rec.itemId || rec.item?.id || path.basename(f, ".json");
  const label = rec.item?.title || itemId;
  if (!rec.coverage?.complete) {
    console.log(`SKIP  ${label} — capture incomplete (${rec.coverage?.reason || "no reason recorded"})`);
    continue;
  }
  const assets = [];
  let failed = false;
  for (const res of rec.resources || []) {
    if (!res.sha256) {
      // A redirect entry carries no body; record it without a cid.
      assets.push({ url: res.url, status: res.status, redirectTo: res.redirectTo });
      continue;
    }
    const blobPath = path.join(blobsDir, res.sha256);
    let bytes;
    try {
      bytes = await readFile(blobPath);
    } catch {
      console.log(`FAIL  ${label} — blob missing for ${res.url} (${res.sha256.slice(0, 12)}…)`);
      failed = true;
      continue;
    }
    const digest = createHash("sha256").update(bytes).digest("hex");
    if (digest !== res.sha256) {
      console.log(`FAIL  ${label} — blob hash mismatch for ${res.url}`);
      failed = true;
      continue;
    }
    const cid = await ipfsAdd(bytes, res.sha256);
    assets.push({
      url: res.url,
      method: res.method || undefined,
      status: res.status,
      contentType: res.contentType || undefined,
      sha256: res.sha256,
      bytes: bytes.length,
      cid,
    });
    console.log(`ok    ${cid}  ${(res.contentType || "").padEnd(24).slice(0, 24)}  ${res.url.slice(0, 60)}`);
  }
  if (failed) {
    console.log(`SKIP  ${label} — not exporting a manifest with missing pieces`);
    continue;
  }
  const manifest = {
    assetsVersion: "0.0.1-draft",
    itemId,
    item: rec.item,
    entry: rec.entry,
    capturedAt: rec.capturedAt,
    capturedBy: "feral-controld offlinecache (observed at runtime)",
    coverage: rec.coverage,
    assets,
  };
  const body = JSON.stringify(manifest, null, 2) + "\n";
  const outPath = path.join(outDir, `${itemId}.assets.json`);
  await writeFile(outPath, body);
  const manifestCid = await ipfsAdd(Buffer.from(body), "assets.json");
  console.log(`\n${label}`);
  console.log(`  manifest: ${outPath}`);
  console.log(`  manifest CID: ${manifestCid}`);
  console.log(`  assets: ${assets.filter((a) => a.cid).length} content-addressed, all pinned locally`);
}
