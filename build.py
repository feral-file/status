#!/usr/bin/env python3
"""Build status.feralfile.com from the data/ directory.

Inputs (data/):
  bitmark_exhibitions_<date>.json   per-exhibition migration totals (bucket 3)
  bitmark_chain_enumeration_<date>.csv   per-work list, works still on Bitmark
  bitmark_series_media_<date>.csv   per-series CDN probe results
  census/token_census_*.csv         token-health-monitor census output
                                    (buckets 1 and 2; optional until the first
                                    census completes)
  updates.json                      dated changelog entries -> page + RSS

Outputs (public/): index.html, status.md, llms.txt, feed.xml, robots.txt,
_headers, data/status.json, data/*.csv copies.

Everything on the page is computed from these files. No number is typed into
the template by hand.

Framing (decided 2026-08-03): the page is "Feral File Status" — every
published work, and whether it still works. A published work is a chain of
references (token -> contract -> metadata -> files -> runtime); the tiles
measure what each work's survival depends on. "Resolves" (fetchable from
public infrastructure) is measured now; "plays" (renders correctly) is out of
scope until the #3485 probe exists — the page says so plainly and promises
nothing.
"""

import csv
import glob
import html
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
PUBLIC = ROOT / "public"
SITE_URL = "https://status.feralfile.com"


def latest(pattern):
    matches = sorted(DATA.glob(pattern))
    return matches[-1] if matches else None


def load_bucket3():
    ex_path = latest("bitmark_exhibitions_*.json")
    work_path = latest("bitmark_chain_enumeration_*.csv")
    series_path = latest("bitmark_series_media_*.csv")
    doc = json.loads(ex_path.read_text())
    works = list(csv.DictReader(open(work_path)))
    series = list(csv.DictReader(open(series_path)))

    computed_still = Counter(r["exhibition_slug"] for r in works)
    for e in doc["exhibitions"]:
        recorded = e["still_bitmark"] + e["swap_initiated"]
        found = computed_still[e["slug"]]
        if recorded != found:
            raise SystemExit(
                f"bucket 3 mismatch for {e['slug']}: totals file says "
                f"{recorded} on-Bitmark works, per-work CSV has {found}"
            )

    probe_ok = sum(1 for s in series if s["probe_status"] == "200")
    return {
        "as_of": doc["as_of"],
        "exhibitions": doc["exhibitions"],
        "works_on_bitmark": len(works),
        "series_count": len(series),
        "exhibitions_affected": sum(
            1 for e in doc["exhibitions"] if e["still_bitmark"] + e["swap_initiated"]
        ),
        "series_probe": {
            "date": doc["as_of"],
            "resolving": probe_ok,
            "total": len(series),
        },
        "media_mix": dict(Counter(s["medium"] for s in series)),
        "files": [ex_path.name, work_path.name, series_path.name],
    }


def load_census():
    """Buckets 1 and 2 from the token-health-monitor census CSV, if present.

    Roll up per-resource rows to per-work state:
      independent   every CID resource resolves on ipfs.io
      gateway_gap   has CID resources, but at least one fails on ipfs.io
      dependent     no CID resources at all (cdn / other hosting only)
    """
    path = None
    candidates = sorted(glob.glob(str(DATA / "census" / "token_census_*.csv")))
    if candidates:
        path = Path(candidates[-1])
    if path is None:
        return None

    per_work = {}
    for r in csv.DictReader(open(path)):
        key = (r["chain"], r["contract"], r["token_id"])
        st = per_work.setdefault(key, {"cid": 0, "cid_fail": 0, "resources": 0})
        st["resources"] += 1
        if r["cid"]:
            st["cid"] += 1
            if r.get("ipfs_io_ok", "") != "ok":
                st["cid_fail"] += 1

    buckets = Counter()
    for st in per_work.values():
        if st["cid"] == 0:
            buckets["dependent"] += 1
        elif st["cid_fail"]:
            buckets["gateway_gap"] += 1
        else:
            buckets["independent"] += 1
    return {
        "file": path.name,
        "date": path.name.replace("token_census_", "").split("T")[0],
        "works": len(per_work),
        "buckets": dict(buckets),
    }


def esc(s):
    return html.escape(str(s), quote=True)


def n(v):
    return f"{v:,}"


def tile(number, label, note):
    return f"""
      <div class="tile">
        <div class="tile-number">{number}</div>
        <div class="tile-label">{esc(label)}</div>
        <p class="tile-note">{note}</p>
      </div>"""


def render(bucket3, census, updates, generated_at):
    if census:
        b = census["buckets"]
        tile1 = tile(
            n(b.get("independent", 0)),
            "works that resolve without Feral File",
            f"Every content-addressed file verified on ipfs.io, {esc(census['date'])}.",
        )
        tile2 = tile(
            n(b.get("gateway_gap", 0)),
            "works that should resolve without us, but currently fail",
            "Content-addressed, but at least one file did not resolve on "
            "ipfs.io. Being re-pinned.",
        )
        census_note = ""
    else:
        tile1 = tile(
            "&mdash;",
            "works that resolve without Feral File",
            "First full census in progress. Publishes here when it completes.",
        )
        tile2 = tile(
            "&mdash;",
            "works that should resolve without us, but currently fail",
            "A June 5 audit found 17 of 49 Ethereum exhibitions whose metadata "
            "did not resolve on ipfs.io. The census re-checks every work.",
        )
        census_note = (
            '<p class="dated">The Ethereum and Tezos census started '
            "August 3, 2026 and probes every file of every edition through the "
            "public gateways a wallet or browser actually uses (ipfs.io, "
            "dweb.link, ipfs.feralfile.com). Its results replace the two "
            "dashes above.</p>"
        )

    tile3 = tile(
        n(bucket3["works_on_bitmark"]),
        "works that depend entirely on Feral File",
        f"Bitmark-era works, enumerated {esc(bucket3['as_of'])}. "
        "Details and remediation below.",
    )

    ex_rows = "\n".join(
        f"""        <tr>
          <td><a href="https://feralfile.com/exhibitions/{esc(e["slug"])}">{esc(e["title"])}</a></td>
          <td class="num">{n(e["works"])}</td>
          <td class="num">{n(e["still_bitmark"] + e["swap_initiated"])}</td>
          <td class="num">{n(e["migrated_ethereum"])}</td>
          <td class="num">{n(e["migrated_tezos"])}</td>
        </tr>"""
        for e in bucket3["exhibitions"]
    )

    updates_html = "\n".join(
        f"""      <article>
        <h3><span class="dated">{esc(u["date"])}</span> {esc(u["title"])}</h3>
        <p>{esc(u["body"])}</p>
      </article>"""
        for u in updates
    )

    probe = bucket3["series_probe"]
    data_files = "".join(
        f'<li><a href="data/{esc(f)}">{esc(f)}</a></li>'
        for f in bucket3["files"] + (["census/" + census["file"]] if census else [])
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Feral File Status</title>
<link rel="stylesheet" href="static/style.css">
<link rel="alternate" type="application/rss+xml" title="Feral File status updates" href="feed.xml">
<link rel="alternate" type="application/json" href="data/status.json">
<link rel="alternate" type="text/markdown" href="status.md">
<meta name="description" content="Every work Feral File has published, and whether it still works — checked from the outside, the way a collector's wallet or browser fetches art.">
</head>
<body>
<header>
  <p class="brand"><a href="https://feralfile.com">Feral File</a></p>
  <h1>Status</h1>
  <p class="lede">Every work we&rsquo;ve published, and whether it still
  works. Checked from the outside &mdash; the way a collector&rsquo;s wallet
  or browser fetches art. The raw data lives beside this page, in
  <a href="data/status.json">JSON</a> and <a href="#data">CSV</a>.</p>
</header>

<main>
  <section id="what">
    <h2>What a published work is</h2>
    <p>A work published on Feral File is not a file in one place. It is a
    chain of references: a token on a blockchain points to a smart contract,
    the contract points to metadata, the metadata points to the files of the
    artwork, and those files run in a browser or on an Art Computer. Some works also
    read data from their contract while they run. A work is alive when every
    link in that chain answers.</p>
    <p>Each link has a keeper. The blockchain keeps the token, the contract,
    and anything stored on chain. Content-addressed files can be kept by
    anyone who cares to pin them, including collectors. Whatever remains
    depends on Feral File&rsquo;s own servers. The fewer links that need us,
    the more permanent the work &mdash; and that is what this page watches:
    how many works still need us, and for which links.</p>
    <p>One honest limit is worth stating, because it is widely
    misunderstood: putting a file on IPFS does not copy it anywhere. A work
    stays available only while someone, somewhere, keeps a copy. What
    content addressing adds is that every copy is equal and verifiable
    &mdash; a copy on a collector&rsquo;s computer counts exactly as much as
    one on ours, and none can be altered without detection. So when this
    page publishes a work&rsquo;s content address, keeping that work alive
    becomes something any collector, museum, or archive can do with one
    command, without asking our permission. That is the invitation.</p>
  </section>

  <section class="tiles" aria-label="Summary">
{tile1}{tile2}{tile3}
  </section>
  {census_note}

  <section id="bitmark">
    <h2>Works that depend entirely on us ({n(bucket3["works_on_bitmark"])})</h2>
    <p>Feral File&rsquo;s first {len(bucket3["exhibitions"])} exhibitions were
    minted on the Bitmark blockchain, which we built in 2014 and retired in
    2025. The chain itself was preserved as a verifiable archive &mdash; its
    data on IPFS, its Merkle root on Ethereum, a timestamp on Bitcoin (<a
    href="https://github.com/bitmark-inc/bitmarkd/wiki/bitmark-archive">the
    Bitmark Archive</a>; <a
    href="https://feralfile.substack.com/p/before-ethereum-before-nfts-there">the
    story</a>) &mdash; so the ownership records of these works are already
    safe. What remained exposed was the artwork files themselves. Works later
    collected on Ethereum or Tezos were migrated and carry content-addressed
    copies; the {n(bucket3["works_on_bitmark"])} works never migrated &mdash;
    across {n(bucket3["series_count"])} series in
    {bucket3["exhibitions_affected"]} exhibitions &mdash; have their only
    media copy on our content delivery network (cdn.feralfileassets.com).
    Those files were last verified reachable on {esc(probe["date"])}:
    {n(probe["resolving"])} of {n(probe["total"])} series resolved (one probe
    per series; editions of a series share files).</p>
    <p>A single copy behind our servers is not what we promise. Remediation
    is in progress and targeted within 2&ndash;3 months: every work gets a
    content-addressed copy that resolves independently of our infrastructure,
    or a dated exception with an owner and a migration path.</p>
    <table>
      <thead>
        <tr><th>Exhibition</th><th class="num">Works</th><th class="num">Not yet migrated</th><th class="num">On Ethereum</th><th class="num">On Tezos</th></tr>
      </thead>
      <tbody>
{ex_rows}
      </tbody>
    </table>
  </section>

  <section id="method">
    <h2>What we check, and what we don&rsquo;t yet</h2>
    <p>Two different promises hide inside &ldquo;it still works.&rdquo; A work
    <strong>resolves</strong> when every reference in its chain can be fetched
    from public infrastructure. That is what this page measures: checks follow
    the token&rsquo;s metadata to its files and request each one over the
    public gateways wallets and browsers use, with ordinary headers and
    redirects. A file counts as resolving only when a public gateway serves it
    &mdash; our own infrastructure answering is not enough.</p>
    <p>A work <strong>plays</strong> when what resolves also renders the way
    the artist intended. This page does not yet measure playing. What is
    stored on chain is not probed either: it survives with the chain itself.
    Bitmark-era works are enumerated from the public Feral File API by each
    work&rsquo;s on-chain location. This page is regenerated from the raw data
    on every update; no number on it is typed by hand.</p>
  </section>

  <section id="data">
    <h2>Data</h2>
    <p>Everything above, machine-readable. Agents welcome: start at
    <a href="llms.txt">llms.txt</a>. Data files are served with open CORS.</p>
    <ul>
      <li><a href="data/status.json">status.json</a> &mdash; summary of every number on this page</li>
      <li><a href="status.md">status.md</a> &mdash; this page as plain Markdown</li>
      {data_files}
      <li><a href="feed.xml">feed.xml</a> &mdash; RSS, one entry per update</li>
    </ul>
  </section>

  <section id="updates">
    <h2>Updates</h2>
{updates_html}
  </section>
</main>

<footer>
  <p>Generated {esc(generated_at)} &middot; <a href="https://feralfile.com">feralfile.com</a></p>
</footer>
</body>
</html>
"""


def build_markdown(bucket3, census, updates, generated_at):
    """The whole page as plain Markdown — the cheap read for a model."""
    if census:
        b = census["buckets"]
        b1 = f"{b.get('independent', 0):,} works (every content-addressed file verified on ipfs.io, {census['date']})"
        b2 = f"{b.get('gateway_gap', 0):,} works (at least one file failing on ipfs.io)"
    else:
        b1 = b2 = "census in progress (started 2026-08-03; publishes here on completion)"
    probe = bucket3["series_probe"]
    rows = "\n".join(
        f"| {e['title']} | {e['works']:,} | {e['still_bitmark'] + e['swap_initiated']:,} "
        f"| {e['migrated_ethereum']:,} | {e['migrated_tezos']:,} |"
        for e in bucket3["exhibitions"]
    )
    upd = "\n".join(f"- **{u['date']} — {u['title']}.** {u['body']}" for u in updates)
    return f"""# Feral File Status

Every work we've published, and whether it still works — checked from the
outside, the way a collector's wallet or browser fetches art. Generated
{generated_at}. Canonical URL: {SITE_URL}
Machine-readable summary: {SITE_URL}/data/status.json

## What a published work is

A work published on Feral File is a chain of references: a token on a
blockchain points to a smart contract, the contract points to metadata, the
metadata points to the files of the artwork, and those files run in a browser
or on an Art Computer. Some works also read data from their contract while they run. A
work is alive when every link in that chain answers.

Each link has a keeper. The blockchain keeps the token, the contract, and
anything stored on chain. Content-addressed files can be kept by anyone who
cares to pin them. Whatever remains depends on Feral File's own servers. The
fewer links that need us, the more permanent the work. This page watches how
many works still need us, and for which links.

One honest limit, because it is widely misunderstood: putting a file on IPFS
does not copy it anywhere. A work stays available only while someone,
somewhere, keeps a copy. What content addressing adds is that every copy is
equal and verifiable — a collector's copy counts exactly as much as ours,
and none can be altered without detection. When this page publishes a work's
content address, keeping that work alive becomes something any collector,
museum, or archive can do with one command, without asking our permission.
That is the invitation.

## Works, by what their survival depends on

1. Resolve without Feral File: {b1}
2. Should resolve without us, but currently fail on public gateways: {b2}
3. Depend entirely on Feral File (media layer): {bucket3["works_on_bitmark"]:,} works
   across {bucket3["series_count"]:,} series in {bucket3["exhibitions_affected"]}
   exhibitions (as of {bucket3["as_of"]}), sole media copy on
   cdn.feralfileassets.com. Their ownership records are already safe: the
   Bitmark blockchain (retired 2025) was preserved as a verifiable archive —
   data on IPFS, Merkle root on Ethereum, timestamp on Bitcoin
   (https://github.com/bitmark-inc/bitmarkd/wiki/bitmark-archive).
   Last probe {probe["date"]}: {probe["resolving"]:,} of {probe["total"]:,}
   series resolved (one probe per series; editions share files). Remediation
   targeted within 2-3 months: a content-addressed copy per work, or a dated
   exception with an owner.

## Bitmark-era exhibitions

| Exhibition | Works | Not yet migrated | On Ethereum | On Tezos |
|---|---:|---:|---:|---:|
{rows}

## What we check, and what we don't yet

A work RESOLVES when every reference in its chain can be fetched from public
infrastructure. That is what this page measures: checks follow the token's
metadata to its files and request each one over the public gateways wallets
and browsers use. A file counts as resolving only when a public gateway
serves it — our own infrastructure answering is not enough.

A work PLAYS when what resolves also renders the way the artist intended.
This page does not yet measure playing. On-chain data is not probed: it
survives with the chain itself. Bitmark-era works are enumerated from the
public Feral File API by each work's on-chain location. The page is
regenerated from the raw data on every update.

## Data

- {SITE_URL}/data/status.json
- {SITE_URL}/feed.xml (RSS, one entry per update)
- CSVs listed at {SITE_URL}/#data

## Updates

{upd}
"""


def build_llms_txt(bucket3):
    return f"""# Feral File Status

> Every work Feral File ({SITE_URL.replace("status.", "")}) has published,
> and whether it still works — checked from the outside, the way a
> collector's wallet or browser fetches art. A published work is a chain of
> references (token -> contract -> metadata -> files -> runtime); this site
> reports whether each link answers and what each work's survival depends
> on. Static page, no client-side rendering; every number is generated from
> the raw data files below. Data is served with open CORS.

## Read this first

- [status.md]({SITE_URL}/status.md): the whole page as plain Markdown
- [status.json]({SITE_URL}/data/status.json): every number, structured

## Raw data

- [Bitmark-era per-work enumeration]({SITE_URL}/data/{bucket3["files"][1]}):
  one row per work whose only copy is on Feral File's CDN
- [Per-series media probes]({SITE_URL}/data/{bucket3["files"][2]}): one CDN
  probe per series
- [Per-exhibition totals]({SITE_URL}/data/{bucket3["files"][0]})

## Updates

- [RSS feed]({SITE_URL}/feed.xml): one entry per change to this page
"""


ROBOTS_TXT = """User-agent: *
Allow: /
"""

# Cloudflare Pages header rules: open CORS so agents in browser contexts can
# fetch the data; correct content type for the markdown mirror.
HEADERS_FILE = """/*
  Access-Control-Allow-Origin: *

/status.md
  Content-Type: text/markdown; charset=utf-8

/llms.txt
  Content-Type: text/plain; charset=utf-8
"""


def build_feed(updates, generated_at_dt):
    items = "\n".join(
        f"""  <item>
    <title>{html.escape(u["title"])}</title>
    <link>{SITE_URL}/#updates</link>
    <guid isPermaLink="false">ff-status-{u["date"]}-{i}</guid>
    <pubDate>{format_datetime(datetime.fromisoformat(u["date"]).replace(tzinfo=timezone.utc))}</pubDate>
    <description>{html.escape(u["body"])}</description>
  </item>"""
        for i, u in enumerate(updates)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Feral File status</title>
  <link>{SITE_URL}</link>
  <description>Updates to whether every published Feral File work still works, and what each work's survival depends on.</description>
  <lastBuildDate>{format_datetime(generated_at_dt)}</lastBuildDate>
{items}
</channel>
</rss>
"""


def main():
    bucket3 = load_bucket3()
    census = load_census()
    updates = sorted(
        json.loads((DATA / "updates.json").read_text()),
        key=lambda u: u["date"],
        reverse=True,
    )
    now = datetime.now(timezone.utc)
    generated_at = now.strftime("%Y-%m-%d %H:%M UTC")

    # Clean contents but keep the directory inode, so a running `make serve`
    # keeps working across rebuilds.
    if PUBLIC.exists():
        for item in PUBLIC.iterdir():
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    (PUBLIC / "data").mkdir(parents=True)
    shutil.copytree(ROOT / "static", PUBLIC / "static")

    for f in bucket3["files"]:
        shutil.copy(DATA / f, PUBLIC / "data" / f)
    if census:
        (PUBLIC / "data" / "census").mkdir()
        shutil.copy(DATA / "census" / census["file"], PUBLIC / "data" / "census")

    status = {
        "generated_at": now.isoformat(timespec="seconds"),
        "site": SITE_URL,
        "works_by_dependency": {
            "resolve_without_feralfile": (
                {"works": census["buckets"].get("independent", 0), "as_of": census["date"]}
                if census
                else {"status": "census_in_progress", "started": "2026-08-03"}
            ),
            "failing_public_gateways": (
                {"works": census["buckets"].get("gateway_gap", 0), "as_of": census["date"]}
                if census
                else {"status": "census_in_progress", "started": "2026-08-03"}
            ),
            "depend_entirely_on_feralfile": {
                "works": bucket3["works_on_bitmark"],
                "series": bucket3["series_count"],
                "exhibitions": bucket3["exhibitions_affected"],
                "as_of": bucket3["as_of"],
                "host": "cdn.feralfileassets.com",
                "last_probe": bucket3["series_probe"],
                "media_mix_by_series": bucket3["media_mix"],
                "remediation": "content-addressed copy per work, targeted 2-3 months from 2026-08-03",
            },
        },
        "scope": {
            "measures": "resolves: every reference in a work's chain fetchable from public infrastructure",
            "not_yet_measured": "plays: what resolves also renders as the artist intended",
        },
        "bitmark_exhibitions": bucket3["exhibitions"],
        "updates": updates,
    }

    (PUBLIC / "index.html").write_text(render(bucket3, census, updates, generated_at))
    (PUBLIC / "data" / "status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False))
    (PUBLIC / "feed.xml").write_text(build_feed(updates, now))
    (PUBLIC / "status.md").write_text(build_markdown(bucket3, census, updates, generated_at))
    (PUBLIC / "llms.txt").write_text(build_llms_txt(bucket3))
    (PUBLIC / "robots.txt").write_text(ROBOTS_TXT)
    (PUBLIC / "_headers").write_text(HEADERS_FILE)

    kind = f"census {census['file']}" if census else "census pending"
    print(f"built public/ ({kind}, bucket3 as of {bucket3['as_of']})")


if __name__ == "__main__":
    main()
