#!/usr/bin/env node
// Verify every signature on a witness entry. Zero dependencies, Node >= 18.
//
//   node tools/witness/verify.mjs data/witness/<entry>.json
//   curl -s https://status.feralfile.com/data/witness/<entry>.json | node tools/witness/verify.mjs -
//
// Exit 0 when every signature verifies and the payload hash matches, 1 otherwise.
// What is checked, per signature: `payload_hash` equals sha256 of the canonical
// document (see sign.mjs for the exact bytes), and `sig` is a valid Ed25519
// signature of that digest by the public key encoded in `kid` (did:key).

import { readFileSync } from "node:fs";
import { createPublicKey, verify } from "node:crypto";
import { signingDigest } from "./sign.mjs";

const ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
const SPKI_PREFIX = Buffer.from("302a300506032b6570032100", "hex");

function base58decode(s) {
  let n = 0n;
  for (const c of s) { const d = ALPHABET.indexOf(c); if (d < 0) throw new Error("bad base58"); n = n * 58n + BigInt(d); }
  let hex = n.toString(16); if (hex.length % 2) hex = "0" + hex;
  let out = Buffer.from(hex, "hex");
  let zeros = 0; for (const c of s) { if (c !== "1") break; zeros++; }
  return Buffer.concat([Buffer.alloc(zeros), out]);
}

function publicKeyFromDidKey(kid) {
  if (!kid.startsWith("did:key:z")) throw new Error("kid is not a base58btc did:key");
  const data = base58decode(kid.slice("did:key:z".length));
  if (data.length !== 34 || data[0] !== 0xed || data[1] !== 0x01) throw new Error("kid is not ed25519-pub");
  return createPublicKey({ key: Buffer.concat([SPKI_PREFIX, data.subarray(2)]), format: "der", type: "spki" });
}

const src = process.argv[2];
if (!src) { console.error("usage: verify.mjs <entry.json | ->"); process.exit(2); }
const doc = JSON.parse(readFileSync(src === "-" ? 0 : src, "utf8"));
if (!Array.isArray(doc.signatures) || doc.signatures.length === 0) { console.error("no signatures[]"); process.exit(1); }
const digest = signingDigest(doc);
let ok = true;
for (const s of doc.signatures) {
  let r;
  try {
    const hashOk = s.payload_hash === "sha256:" + digest.toString("hex");
    const sigOk = s.alg === "ed25519" && verify(null, digest, publicKeyFromDidKey(s.kid), Buffer.from(s.sig, "base64url"));
    r = { kid: s.kid, role: s.role, ts: s.ts, payload_hash_matches: hashOk, signature_valid: sigOk };
    ok = ok && hashOk && sigOk;
  } catch (e) { r = { kid: s.kid, role: s.role, error: e.message }; ok = false; }
  console.log(JSON.stringify(r));
}
console.log(ok ? "OK: every signature verifies" : "FAIL");
process.exit(ok ? 0 : 1);
