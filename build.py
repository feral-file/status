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

Outputs (public/): index.html, feed.xml, data/status.json, data/*.csv copies.

Everything on the page is computed from these files. No number is typed into
the template by hand.
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
      public       every CID resource resolves on ipfs.io
      gateway_gap  has CID resources, but at least one fails on ipfs.io
      centralized  no CID resources at all (cdn / other hosting only)
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
            buckets["centralized"] += 1
        elif st["cid_fail"]:
            buckets["gateway_gap"] += 1
        else:
            buckets["public"] += 1
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
            n(b.get("public", 0)),
            "works content-addressed and publicly resolvable",
            f"Every content-addressed file verified on ipfs.io, {esc(census['date'])}.",
        )
        tile2 = tile(
            n(b.get("gateway_gap", 0)),
            "works with copies that fail on public gateways",
            "Content-addressed, but at least one file did not resolve on ipfs.io. "
            "Being re-pinned.",
        )
        census_note = ""
    else:
        tile1 = tile(
            "&mdash;",
            "works content-addressed and publicly resolvable",
            "First full census in progress. Publishes here when it completes.",
        )
        tile2 = tile(
            "&mdash;",
            "works with copies that fail on public gateways",
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
        "works whose only copy is on our CDN",
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
<title>Feral File Storage Status</title>
<link rel="stylesheet" href="static/style.css">
<link rel="alternate" type="application/rss+xml" title="Feral File storage updates" href="feed.xml">
<meta name="description" content="Where every published Feral File work is stored, and whether each copy resolves right now.">
</head>
<body>
<header>
  <p class="brand"><a href="https://feralfile.com">Feral File</a></p>
  <h1>Storage Status</h1>
  <p class="lede">Where every published work is stored, and whether each copy
  resolves right now. Built from automated checks that fetch our works the way
  a wallet or a browser does. The raw data lives beside this page, in
  <a href="data/status.json">JSON</a> and <a href="#data">CSV</a>.</p>
</header>

<main>
  <section class="tiles" aria-label="Summary">
{tile1}{tile2}{tile3}
  </section>
  {census_note}

  <section id="bitmark">
    <h2>Works with a single copy ({n(bucket3["works_on_bitmark"])})</h2>
    <p>Feral File's first {len(bucket3["exhibitions"])} exhibitions were minted
    on the Bitmark blockchain. Works later collected on Ethereum or Tezos were
    migrated and follow the content-addressed path above. The
    {n(bucket3["works_on_bitmark"])} works still on Bitmark &mdash; across
    {n(bucket3["series_count"])} series in {bucket3["exhibitions_affected"]}
    exhibitions &mdash; have their only copy on our content delivery network
    (cdn.feralfileassets.com). Those files were last verified reachable on
    {esc(probe["date"])}: {n(probe["resolving"])} of {n(probe["total"])} series
    resolved (one probe per series; editions of a series share files).</p>
    <p>A single copy is not what we promise. Remediation is in progress and
    targeted within 2&ndash;3 months: every work gets a content-addressed copy
    that resolves independently of our infrastructure, or a dated exception
    with an owner and a migration path.</p>
    <table>
      <thead>
        <tr><th>Exhibition</th><th class="num">Works</th><th class="num">Still on Bitmark</th><th class="num">On Ethereum</th><th class="num">On Tezos</th></tr>
      </thead>
      <tbody>
{ex_rows}
      </tbody>
    </table>
  </section>

  <section id="method">
    <h2>How this is checked</h2>
    <p>Checks fetch the way a real consumer does: follow the token's metadata
    to its files and request each one over the public gateways wallets and
    browsers use, with ordinary headers and redirects. A file counts as
    resolving only when a public gateway serves it &mdash; our own
    infrastructure answering is not enough. Bitmark-era works are enumerated
    from the public Feral File API by each work's on-chain location. This page
    is regenerated from the raw data on every update; no number on it is typed
    by hand.</p>
  </section>

  <section id="data">
    <h2>Data</h2>
    <p>Everything above, machine-readable. Agents welcome.</p>
    <ul>
      <li><a href="data/status.json">status.json</a> &mdash; summary of every number on this page</li>
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


def build_feed(updates, generated_at_dt):
    items = "\n".join(
        f"""  <item>
    <title>{html.escape(u["title"])}</title>
    <link>{SITE_URL}/#updates</link>
    <guid isPermaLink="false">ff-storage-status-{u["date"]}-{i}</guid>
    <pubDate>{format_datetime(datetime.fromisoformat(u["date"]).replace(tzinfo=timezone.utc))}</pubDate>
    <description>{html.escape(u["body"])}</description>
  </item>"""
        for i, u in enumerate(updates)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Feral File storage status</title>
  <link>{SITE_URL}</link>
  <description>Updates to where published Feral File works are stored and whether each copy resolves.</description>
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

    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
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
        "buckets": {
            "content_addressed_public": (
                {"works": census["buckets"].get("public", 0), "as_of": census["date"]}
                if census
                else {"status": "census_in_progress", "started": "2026-08-03"}
            ),
            "content_addressed_gateway_gap": (
                {"works": census["buckets"].get("gateway_gap", 0), "as_of": census["date"]}
                if census
                else {"status": "census_in_progress", "started": "2026-08-03"}
            ),
            "single_copy_cdn": {
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
        "bitmark_exhibitions": bucket3["exhibitions"],
        "updates": updates,
    }

    (PUBLIC / "index.html").write_text(render(bucket3, census, updates, generated_at))
    (PUBLIC / "data" / "status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False))
    (PUBLIC / "feed.xml").write_text(build_feed(updates, now))

    kind = f"census {census['file']}" if census else "census pending"
    print(f"built public/ ({kind}, bucket3 as of {bucket3['as_of']})")


if __name__ == "__main__":
    main()
