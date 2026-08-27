# feralfile-keep

Give it your wallet address. It pins every published Feral File work that
address holds onto your own IPFS node.

> **Name is TBD.** `@feralfile/keep` / `feralfile-keep` is a placeholder while
> the tool is being shaped. Nothing is published to npm yet.

## Use

With a local [kubo](https://github.com/ipfs/kubo) node running (`ipfs daemon`):

```sh
npx @feralfile/keep 0xYourAddress
npx @feralfile/keep tz1YourAddress
npx @feralfile/keep 0xOne tz1Two          # several wallets in one pass
```

Look before you leap:

```sh
npx @feralfile/keep 0xYourAddress --dry-run
```

### Options

| Flag | Meaning |
| :-- | :-- |
| `--dry-run` | enumerate and report, pin nothing |
| `--api <url>` | kubo HTTP API (default `http://127.0.0.1:5001`) |
| `--timeout <seconds>` | per-pin timeout handed to the node |
| `--out <file>` | also write the unique CID list, one per line |
| `--status-url <url>` | published data source (default `https://status.feralfile.com`) |

Exit code is `1` if any pin failed, `0` otherwise.

## What it actually does

1. **Enumerates holdings** from keyless public indexers — Blockscout for
   Ethereum, TzKT for Tezos. No API key, no account, no Feral File server in
   the path.
2. **Joins them** against the census published at `status.feralfile.com`
   (`data/work_index.json` plus per-exhibition shards), fetched at run time
   and never bundled — so the answer is as current as the site, not as old as
   your install.
3. **Pins** each unique content address through your node's HTTP API, then
   reports what landed and how large it was. Editions of the same work share
   files, so the CID count is normally far below the work count.

This is the command-line twin of the wallet lookup on status.feralfile.com
(`static/wallet.js` in this repo). Same enumeration, same join, same numbers.
The one thing it adds is the last mile: the files end up on a disk you control.

## Honest boundaries

- **Works with no published content address are listed, not dropped.** Some
  works have not had their addresses published yet. There is nothing to pin
  for them today; they appear in the report so you know they exist.
- **Bitmark-era works cannot be enumerated from a wallet address at all.**
  Nothing in this tool will find them. Look them up individually by token ID
  on status.feralfile.com.
- **A pin is a copy, not a promise.** A whole-series archival pin can be very
  large and can take a long time on a cold node; `--timeout` bounds it, and a
  timeout is reported as a failure rather than quietly skipped. Re-running is
  cheap and safe.
- **No IPFS node?** The run degrades instead of dying: it writes
  `feralfile-pins.txt` and prints the one-liner to replay later.
- **Your address is never sent to Feral File.** It goes to the chain indexers
  only. The status site is asked for its published data, the same bytes anyone
  gets, with no idea who is asking.
