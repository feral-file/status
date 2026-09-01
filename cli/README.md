# feralfile-keep

Hold your own copies of the art you collect — any platform.

Give it your wallet address. It works out what the address holds, sorts every
token by how well its files can actually be preserved, and pins what can be
pinned onto your own IPFS node.

Feral File's published works are the best-evidenced part of that, not the whole
of it. For those, the census at status.feralfile.com says exactly which files
make the work, so the pin is complete and probed. For everything else the
token's own metadata is the evidence, and the report says so, tier by tier.

## Use

With a local [kubo](https://github.com/ipfs/kubo) node running (`ipfs daemon` —
on Homebrew the formula is `kubo`, and the command it installs is `ipfs`):

```sh
npx @feralfile/keep 0xYourAddress
npx @feralfile/keep tz1YourAddress
npx @feralfile/keep 0xOne tz1Two          # several wallets in one pass
```

Look before you leap:

```sh
npx @feralfile/keep 0xYourAddress --dry-run
```

Keep an assets manifest captured off a device, with or without a wallet:

```sh
npx @feralfile/keep --manifest ./exports/*.assets.json
npx @feralfile/keep 0xYourAddress --manifest ./exports/one.assets.json
```

### Options

| Flag | Meaning |
| :-- | :-- |
| `--manifest <file\|url>` | an assets manifest from `capture-export` (repeatable) |
| `--dry-run` | enumerate and report, pin nothing |
| `--ff-only` | old scope: published Feral File works only |
| `--limit <n>` | trial run — keep at most `n` works per tier |
| `--verbose` | print every work line instead of the first 20 |
| `--api <url>` | kubo HTTP API (default `http://127.0.0.1:5001`) |
| `--timeout <seconds>` | absolute per-pin timeout; without it a pin is failed after 120 s with no data |
| `--out <file>` | also write the unique CID list, one per line |
| `--record <file>` | where to write the kept record (default `keep-record.json`) |
| `--status-url <url>` | published data source (default `https://status.feralfile.com`) |

`--limit` is for trial runs. It caps how many works each tier contributes, so
you can watch a small mixed slice land before committing to a whole wallet. The
tier counts still report the full wallet — only the keeping is limited.

Exit code is `1` if any pin failed, `0` otherwise.

## The tiers

Every token the wallet holds lands in exactly one tier, and every tier is
reported. The order is an evidence order: how much the tool can honestly claim
about what a pin preserves.

| Tier | What it means | What happens |
| :-- | :-- | :-- |
| **observed** | Came from a `--manifest` — the file list a device actually fetched while the work ran | Pins every captured file |
| **verified** | Matched the published Feral File census — the file list is known and probed | Pins the census-listed files |
| **content-addressed** | Any other token whose metadata yields at least one IPFS reference | Pins what the metadata declares |
| **on-chain** | Metadata and media are `data:` URIs or inline (an on-chain SVG, say) | Nothing to pin — it survives with the chain |
| **mutable-only** | Metadata exists, but every media reference is a plain https URL | Cannot be kept, only bookmarked; the domains are listed |
| **unresolved** | No usable metadata | Listed with a count |

A wallet report opens with the tally of the five wallet tiers:

```
14,897 tokens held → verified 2,411 · content-addressed 7,801 · on-chain 0 · mutable-only 4,685 · unresolved 0
```

`observed` is not a wallet tier — a manifest is an input, not a holding — so it
gets its own section in the report.

References are recognized as `ipfs://<cid>`, `ipfs://<cid>/<path>`, and gateway
URLs of the form `…/ipfs/<cid>…` on any host. CIDs are validated before they
are handed to a node — a gateway-shaped URL whose "CID" does not parse is not
pinned, because a wrong pin looks like success.

A reference of the form `<cid>/<path>` names one file inside a directory that
often holds thousands of other people's tokens. Those are resolved to their own
CID through your node first. If the resolve fails — or on `--dry-run`, where
there is no node to ask — the reference is reported as needing resolution and
the directory root is **not** pinned in its place.

## What it actually does

1. **Enumerates holdings** from keyless public indexers — Blockscout for
   Ethereum, TzKT for Tezos. No API key, no account, no Feral File server in
   the path. Both indexers return each token's metadata on the same rows that
   carry the balances, so the wider scope costs no extra API calls.
2. **Joins them** against the census published at `status.feralfile.com`
   (`data/work_index.json` plus per-exhibition shards), fetched at run time
   and never bundled — so the answer is as current as the site, not as old as
   your install. That join is the verified tier.
3. **Sorts the rest by evidence** into the tiers above, straight from the
   metadata the indexers already handed over.
4. **Pins** each unique content address through your node's HTTP API, then
   reports what landed and how large it was. Editions of the same work share
   files, so the CID count is normally far below the work count.

Internally each of those is a *resolver* producing one DP-1-shaped record per
work, and the pinner reads only those records — it never learns what a census
is. [ARCHITECTURE.md](ARCHITECTURE.md) is the one page on why.

`--ff-only` restores the original scope: the census join alone, nothing else
examined. It also skips fetching metadata, so it is the faster run.

## What you keep

After a real (non-`--dry-run`) run it writes `keep-record.json` — a DP-1
playlist with one item per work that actually has a pin on this disk, each
carrying its provenance, the evidence it was kept on, and the content addresses
that landed:

```json
{
  "dpVersion": "1.0.0",
  "title": "Kept — feralfile-keep",
  "items": [
    {
      "id": "eip155:1:erc721:0xa7d8…D270:78000905",
      "title": "Fidenza #905",
      "source": "https://generator.artblocks.io/1/0xa7d8…/78000905",
      "provenance": { "type": "onChain", "contract": { "chain": "evm", "…": "…" } },
      "evidence": "observed",
      "assets": [ { "url": "…", "sha256": "…", "cid": "bafkrei…" } ]
    }
  ]
}
```

Only CIDs that pinned successfully appear — listing an address that failed
would claim you keep something you do not. The record is rewritten after every
successful pin, so an interrupted run still says exactly what landed. There
are no signatures: nothing in it is a claim about anyone but the person who
ran it.

The verified tier is the command-line twin of the wallet lookup on
status.feralfile.com (`static/wallet.js` in this repo). Same enumeration, same
join, same numbers. The one thing it adds is the last mile: the files end up on
a disk you control.

## Honest boundaries

- **The content-addressed tier keeps what the metadata declares.** That is the
  real limit of the wider scope. A code-based work's undeclared dependencies —
  a library it fetches at run time, a font, an API it calls — are not captured
  by pinning what the metadata names. The pin is what the token points at, not
  a guarantee the work still runs.
- **Bitmark-era works cannot be enumerated from a wallet address at all.**
  Nothing in this tool will find them. Look them up individually by token ID
  on status.feralfile.com.
- **Mutable-only means bookmarked, not kept.** Whoever runs those domains can
  change or withdraw the files at any time. The tier exists so you can see how
  much of a collection sits on that footing.
- **An observed capture is one run of the work.** It is the strongest evidence
  here — it includes the dependencies nobody declared — but a work that fetches
  something new on a later run has files no earlier capture holds.
- **Works with no published content address are listed, not dropped.** Some
  verified works have not had their addresses published yet. There is nothing
  to pin for them today; they appear in the report so you know they exist.
- **A pin is a copy, not a promise.** A whole-series archival pin can be very
  large and can take a long time on a cold node; it keeps running as long as
  data keeps arriving, and a pin that delivers nothing for 120 seconds is
  failed and reported rather than quietly skipped (`--timeout` sets an
  absolute limit instead). Re-running is cheap and safe.
- **No IPFS node?** The run degrades instead of dying: it writes
  `feralfile-pins.txt` and prints the one-liner to replay later.
- **Your address is never sent to Feral File.** It goes to the chain indexers
  only. The status site is asked for its published data, the same bytes anyone
  gets, with no idea who is asking.

## Why this exists

DP-1 is about distributing, verifying, and preserving blockchain-native digital
art. Keep is the collector side of the third verb. Preservation that only an
institution can perform is not preservation; it is a dependency. This puts the
copy on a disk the collector owns, and is honest about the cases where no copy
is possible.
