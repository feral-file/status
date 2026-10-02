#!/usr/bin/env node
// Sign a witness entry with an Ed25519 key, in the DP-1 v1.1.0 signature
// envelope (the same one ff-cli puts on playlists), so one verifier reads both.
//
//   node tools/witness/sign.mjs data/witness/<entry>.json --key-file ~/.config/ff-witness.key
//   node tools/witness/sign.mjs data/witness/<entry>.json --ff-cli-config   # the key ff-cli signs playlists with
//
// Key material: a 32-byte Ed25519 seed as hex, PKCS#8 DER as base64, or PEM.
// The signature is appended to `signatures[]`; a second party signs the same
// file with their own key and appends their own. The signed bytes are the
// document minus `signature`/`signatures`, canonicalized (keys sorted
// recursively, no whitespace), plus one "\n", hashed with SHA-256; the Ed25519
// signature is over that 32-byte digest. `kid` is the signer's public key as
// did:key (multicodec ed25519-pub, base58btc). Zero dependencies, Node >= 18.

import { readFileSync, writeFileSync } from "node:fs";
import { createHash, createPrivateKey, createPublicKey, sign } from "node:crypto";
import { homedir } from "node:os";
import { join } from "node:path";

const ROLE = "witness";
const ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
const PKCS8_PREFIX = Buffer.from("302e020100300506032b657004220420", "hex");

export function canonicalize(v) {
  if (v === null) return "null";
  if (typeof v === "string") return JSON.stringify(v);
  if (typeof v === "number") {
    if (!Number.isFinite(v)) throw new Error("non-finite number");
    return JSON.stringify(v);
  }
  if (typeof v === "boolean") return v ? "true" : "false";
  if (Array.isArray(v)) return `[${v.map(canonicalize).join(",")}]`;
  if (typeof v === "object")
    return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canonicalize(v[k])}`).join(",")}}`;
  throw new Error(`unsupported value: ${typeof v}`);
}

export function signingDigest(doc) {
  const body = { ...doc };
  delete body.signature;
  delete body.signatures;
  return createHash("sha256").update(Buffer.concat([Buffer.from(canonicalize(body), "utf8"), Buffer.from("\n")])).digest();
}

export function base58(buf) {
  let n = BigInt("0x" + buf.toString("hex"));
  let s = "";
  while (n > 0n) { s = ALPHABET[Number(n % 58n)] + s; n /= 58n; }
  for (const b of buf) { if (b !== 0) break; s = "1" + s; }
  return s;
}

export function didKey(publicKey) {
  const raw = Buffer.from(publicKey.export({ format: "jwk" }).x, "base64url");
  return "did:key:z" + base58(Buffer.concat([Buffer.from([0xed, 0x01]), raw]));
}

export function loadPrivateKey(material) {
  const m = material.trim();
  if (m.includes("BEGIN")) return createPrivateKey(m);
  const hex = m.replace(/^0x/, "");
  if (/^[0-9a-fA-F]{64}$/.test(hex)) return createPrivateKey({ key: Buffer.concat([PKCS8_PREFIX, Buffer.from(hex, "hex")]), format: "der", type: "pkcs8" });
  const b = Buffer.from(m, "base64");
  if (b.length === 32) return createPrivateKey({ key: Buffer.concat([PKCS8_PREFIX, b]), format: "der", type: "pkcs8" });
  return createPrivateKey({ key: b, format: "der", type: "pkcs8" });
}

function main(argv) {
  const file = argv[0];
  if (!file) throw new Error("usage: sign.mjs <entry.json> (--key-file <path> | --ff-cli-config [path])");
  let material;
  const i = argv.indexOf("--key-file");
  const j = argv.indexOf("--ff-cli-config");
  if (i >= 0 && j >= 0) throw new Error("pass --key-file or --ff-cli-config, not both");
  if (i >= 0) material = readFileSync(argv[i + 1], "utf8");
  else if (j >= 0) {
    const cfg = JSON.parse(readFileSync(argv[j + 1] && !argv[j + 1].startsWith("--") ? argv[j + 1] : join(homedir(), ".config", "ff-cli", "config.json"), "utf8"));
    material = cfg.playlist && cfg.playlist.privateKey;
    if (!material) throw new Error("ff-cli config has no playlist.privateKey");
  } else throw new Error("a key is required: --key-file <path> or --ff-cli-config");

  const priv = loadPrivateKey(material);
  const doc = JSON.parse(readFileSync(file, "utf8"));
  const digest = signingDigest(doc);
  const envelope = {
    alg: "ed25519",
    kid: didKey(createPublicKey(priv)),
    ts: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    payload_hash: "sha256:" + digest.toString("hex"),
    role: ROLE,
    sig: sign(null, digest, priv).toString("base64url"),
  };
  doc.signatures = [...(doc.signatures || []), envelope];
  writeFileSync(file, JSON.stringify(doc, null, 1) + "\n");
  console.log(JSON.stringify({ file, kid: envelope.kid, role: envelope.role, payload_hash: envelope.payload_hash, signatures: doc.signatures.length }, null, 1));
}

if (import.meta.url === `file://${process.argv[1]}`) main(process.argv.slice(2));
