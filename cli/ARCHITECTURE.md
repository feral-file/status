# Architecture

## The contract

Keep pins what DP-1 documents declare. Everything that is not the pinner is a
resolver that produces DP-1 documents.

There is one internal record shape, modelled on a DP-1 playlist item:

```js
{
  id,          // stable item identity
  title,
  source?,     // the URL the work plays from, when one is known
  collection?, // the published grouping it came from (a census exhibition)
  provenance: { chain: "evm" | "tezos", contract, tokenId },
  evidence: "observed" | "declared-complete" | "declared-partial" | "none",
  assets: [ { url?, cid?, path?, sha256?, contentType?, bytes?, status?,
              field?, wholeSeries?, resolvedCid? } ],
  boundary?,   // "<name>: <detail>" — present exactly when evidence is "none"
}
```

An asset with a `cid` can be pinned. An asset with a `cid` *and* a `path` names
one file inside a directory that usually holds thousands of other people's
tokens; only the node can turn that into its own address, and the result lands
on `resolvedCid`. An asset with a `url` and no `cid` is a reference that cannot
be kept — it is carried so the report can name the domains a collection is
leaning on. `field` records which declaration named the asset (`image`,
`animation_url`, a census `res`), so a report can say what decided a token's
tier.

Three resolvers produce these records:

| Resolver | Source | Evidence it can claim |
| :-- | :-- | :-- |
| census | `status.feralfile.com` `work_index.json` + per-exhibition shards | `declared-complete` |
| metadata | the token metadata the chain indexers already returned | `declared-partial`, or `none` |
| manifest | an assets manifest from `capture-export` | `observed` |

Everything after them — collect, resolve paths, pin, report, write the kept
record — reads only records. `collectRecords` asks a record what evidence it
carries and which of its assets have a content address; it has no idea what a
census is. Adding an input means adding a resolver, not touching the pinner.

## The evidence ladder

The four levels are ordered by how much the tool can honestly claim about what
a pin preserves. A tier in the report is a rendering of a level, not a separate
concept: `tierOf()` is the one place the mapping lives.

**`observed`** — a runtime capture. `capture-export` reads a feral-controld
offlinecache store and writes the file list a device actually fetched while the
work ran, each blob hashed and content-addressed. Nothing is inferred; it is a
recording. This is the only level that can include a dependency nobody
declared — the CDN script, the font, the API response.

**`declared-complete`** — the publisher's own complete file list. The Feral
File census says which files make the work, and the addresses have been probed
against gateways. Not "somebody looked", but "the publisher says this is all of
it". Renders as the `verified` tier.

**`declared-partial`** — token metadata. Metadata names the media the token
points at and never the dependencies that media reaches for, so it is partial
by construction, not by accident. Renders as `content-addressed`.

**`none` + a named boundary** — nothing to pin, and the record says why in the
`boundary` string. The name before the colon is the tier: `on-chain` (media is
a `data:` URI, already kept by whoever keeps the chain), `mutable-only` (every
reference is a plain https URL — bookmarkable, not keepable), `unresolved` (no
usable metadata). A `none` record is still a record. Nothing is dropped for
being inconvenient, because the count of what cannot be kept is the most
useful number in the report.

## Why this converges

The ladder is the reason the shape is worth the trouble.

**Ecosystem improvements upgrade evidence without Keep changing.** When a
platform starts publishing a complete file list, its tokens move from
`declared-partial` to `declared-complete` because a resolver reads a better
source — no new tier, no new pinning path, no new report. When a device
captures a work, the same item arrives as `observed`. The pinner never learns
about any of it.

**The scraper only shrinks.** The metadata resolver is the guesswork: a list of
field spellings across two token standards, a CID recogniser, a set of
heuristics for what a string might mean. Every work that gains a real
declaration leaves that path. It is the one part of this tool that is supposed
to get smaller over time, and nothing else depends on its internals.

**Maintenance lands on the spec'd seam.** With one record shape, the churn is
in resolvers, and a resolver's job is fully described by its output. The
expensive kind of change — "the pinner now needs to know about X" — is the kind
this arrangement does not have.

## The two external seams

**`capture-export` ← the FF1 offlinecache store.** Its input contract is the
store exactly as the device writes it: `items/<itemId>.json` plus
`blobs/<sha256>`. It reads that store as-is and never modifies it. Incomplete
captures (`coverage.complete == false`) are reported and skipped — an
incomplete manifest presented as complete would be worse than none.

**The assets manifest → `display-protocol/dp1`.** The manifest
(`assetsVersion`, `itemId`, `item`, `assets[{url, cid, sha256, …}]`) is a
*proposed* DP-1 extension: the fetchable, per-item file list the spec does not
define yet. Ref manifest v0.1.0 is metadata and controls only, and
`repro.assetsSHA256` is a verification hash list, not something you can fetch
from. The schema questions belong in `display-protocol/dp1`, not in this
directory. Keep reads the format; it does not own it.

## The kept record

After a real run, `keep-record.json` (or `--record <path>`) is a DP-1 playlist:
`dpVersion` `1.0.0`, one item per work that actually has a pin on this disk,
each carrying its provenance, the evidence it was kept on, and an `assets`
block mirroring `capture-export`'s shape with the content addresses that
landed. Only successfully pinned CIDs appear — listing an address that failed
would claim you keep something you do not.

There are no signatures. This is v0 of "what you keep is itself a playable
document", and nothing in it is a claim about anyone but the person who ran it.
