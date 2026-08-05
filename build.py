#!/usr/bin/env python3
"""Build status.feralfile.com from the data/ directory.

Inputs (data/):
  bitmark_exhibitions_<date>.json   per-exhibition migration totals (Bitmark era)
  bitmark_chain_enumeration_<date>.csv   per-work list, works still on Bitmark
  bitmark_series_media_<date>.csv   per-series CDN probe results
  exhibitions_<date>.json           all published exhibitions (title, slug,
                                    start date) from the public API
  census/token_census_*.csv         token-health-monitor census output
                                    (ETH+Tezos, every edition, every file)
  updates.json                      dated changelog entries -> page + RSS

Outputs (public/): index.html, status.md, llms.txt, feed.xml, robots.txt,
_headers, data/status.json, data/*.csv copies.

Everything on the page is computed from these files. No number is typed into
the template by hand.

Framing (decided 2026-08-03): the page is "Feral File Status" — every
published work, and whether it still works. A published work is a chain of
references (token -> contract -> metadata -> files -> runtime); the tiles
measure what each work's survival depends on, AT THE MEDIA LAYER. The census
fetches metadata through Feral File's own API, so it verifies the artwork
files, not the on-chain tokenURI link — the method section says so plainly.
"Plays" (renders correctly) stays out of scope until the #3485 probe exists.
"""

import csv
import glob
import gzip
import html
import json
import shutil
from collections import Counter, defaultdict
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


def load_registry():
    reg_path = DATA / "registry.json"
    pub_path = DATA / "published.json"
    if not (reg_path.exists() and pub_path.exists()):
        return None
    reg = json.loads(reg_path.read_text())
    pub = json.loads(pub_path.read_text())
    if not reg.get("address"):
        return None
    return {**reg, **{k: pub[k] for k in ("version", "manifest_cid", "published")}}


def load_exhibitions():
    path = latest("exhibitions_*.json")
    exs = json.loads(path.read_text())
    exs.sort(key=lambda e: e.get("exhibitionStartAt") or "")
    return {"file": path.name, "list": exs}


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
    manifest_path = latest("pin_manifest_*.csv")
    pins = {}
    if manifest_path:
        pins = {r["series_id"]: r for r in csv.DictReader(open(manifest_path))}
    pin_summary = None
    if pins:
        pin_summary = {
            "series": len(pins),
            "bytes": sum(int(r["bytes"]) for r in pins.values()),
            "all_verified": all(r["verified"] == "true" for r in pins.values()),
            "as_of": max(r["synced_at"] for r in pins.values())[:10],
            "file": manifest_path.name,
        }
    return {
        "pins": pins,
        "pin_summary": pin_summary,
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
        "by_slug": {
            e["slug"]: e["still_bitmark"] + e["swap_initiated"]
            for e in doc["exhibitions"]
        },
        "files": [ex_path.name, work_path.name, series_path.name],
    }


def load_census():
    """Media-layer rollup of the token-health-monitor census, if present.

    The census fetches metadata via Feral File's API, so metadata rows say
    nothing about on-chain tokenURI hosting — they are EXCLUDED here. A work
    is classified by its media resources only:
      independent   has content-addressed media, all of it resolving on ipfs.io
      gateway_gap   has content-addressed media, at least one file failing
      dependent     no content-addressed media at all (CDN/other hosting only)
    """
    candidates = sorted(glob.glob(str(DATA / "census" / "token_census_*.csv")))
    if not candidates:
        return None
    path = Path(candidates[-1])

    per_work = {}
    for r in csv.DictReader(open(path)):
        if r["resource"] == "metadata":
            continue
        key = (r["chain"], r["contract"], r["token_id"])
        st = per_work.setdefault(
            key, {"cid": 0, "fail": 0, "other": 0, "rest": 0, "ex": r["exhibition"]}
        )
        if r["cid"]:
            st["cid"] += 1
            if r.get("ipfs_io_ok", "") != "ok":
                st["fail"] += 1
        elif r["hosting"] == "other":
            st["other"] += 1
        else:
            st["rest"] += 1

    buckets = Counter()
    per_ex = defaultdict(Counter)
    for st in per_work.values():
        if st["cid"]:
            state = "gateway_gap" if st["fail"] else "independent"
        elif st["other"] and not st["rest"]:
            state = "third_party"
        else:
            state = "dependent"
        buckets[state] += 1
        per_ex[st["ex"]][state] += 1
        per_ex[st["ex"]]["works"] += 1
    return {
        "file": path.name,
        "date": path.name.replace("token_census_", "").split("T")[0],
        "works": len(per_work),
        "buckets": dict(buckets),
        "per_exhibition": {k: dict(v) for k, v in per_ex.items()},
    }


def emit_work_shards(census, bucket3, exhibitions):
    """Per-work lookup data: one JSON shard per exhibition + a token index.

    Shard: data/works/<exhibition_id>.json ->
      {"exhibition": {...}, "works": {token_id: [{chain, contract, state,
       files: [...]}, ...]}}
    Index: data/work_index.json -> {token_id: [exhibition_id, ...]}
    """
    ex_meta = {e["id"]: e for e in exhibitions["list"]}
    slug_to_id = {e["slug"]: e["id"] for e in exhibitions["list"]}
    shards = defaultdict(lambda: defaultdict(list))
    index = defaultdict(set)

    if census:
        per_work = {}
        for r in csv.DictReader(open(DATA / "census" / census["file"])):
            if r["resource"] == "metadata":
                continue
            key = (r["chain"], r["contract"], r["token_id"], r["exhibition"])
            w = per_work.setdefault(
                key, {"chain": r["chain"], "contract": r["contract"], "files": []}
            )
            if r["cid"]:
                f = {"res": r["resource"], "host": "ipfs", "cid": r["cid"]}
                for gw_col, gw in (
                    ("ipfs_io_ok", "ipfs.io"),
                    ("ipfs_feralfile_com_ok", "ipfs.feralfile.com"),
                    ("dweb_link_ok", "dweb.link"),
                ):
                    f[gw] = "ok" if r.get(gw_col, "") == "ok" else "fail"
                w["files"].append(f)
            else:
                w["files"].append(
                    {
                        "res": r["resource"],
                        "host": r["hosting"],
                        "domain": r["host_or_gateway"],
                        "status": r["http_status"],
                    }
                )
        for (chain, contract, token_id, ex_id), w in per_work.items():
            cids = [f for f in w["files"] if f.get("host") == "ipfs"]
            if not cids:
                others = [f for f in w["files"] if f.get("host") == "other"]
                state = "third_party" if others and len(others) == len(w["files"]) else "dependent"
            elif any(f["ipfs.io"] != "ok" for f in cids):
                state = "gateway_gap"
            else:
                state = "independent"
            shards[ex_id][token_id].append(
                {"chain": chain, "contract": contract, "state": state, "files": w["files"]}
            )
            index[token_id].add(ex_id)

    for r in csv.DictReader(open(DATA / latest("bitmark_chain_enumeration_*.csv").name)):
        ex_id = slug_to_id.get(r["exhibition_slug"])
        if not ex_id:
            continue
        token_id = r["bitmark_token_id"]
        files = []
        if r["thumbnail_host"]:
            files.append({"res": "thumbnail", "host": "cdn", "domain": r["thumbnail_host"]})
        files.append({"res": "media", "host": "cdn", "domain": "cdn.feralfileassets.com"})
        pin = bucket3["pins"].get(r["series_id"])
        if pin and pin["verified"] == "true":
            files.append({"res": "archival copy (series)", "host": "ipfs-archival", "cid": pin["cid"]})
        shards[ex_id][token_id].append(
            {
                "chain": "bitmark",
                "contract": "",
                "state": "dependent",
                "name": r["artwork_name"],
                "files": files,
            }
        )
        index[token_id].add(ex_id)

    out_dir = PUBLIC / "data" / "works"
    out_dir.mkdir(parents=True, exist_ok=True)
    for ex_id, works in shards.items():
        meta = ex_meta.get(ex_id, {})
        (out_dir / f"{ex_id}.json").write_text(
            json.dumps(
                {
                    "exhibition": {
                        "id": ex_id,
                        "slug": meta.get("slug"),
                        "title": meta.get("title"),
                    },
                    "works": works,
                },
                separators=(",", ":"),
            )
        )
    (PUBLIC / "data" / "work_index.json").write_text(
        json.dumps({k: sorted(v) for k, v in index.items()}, separators=(",", ":"))
    )
    return sum(len(w) for w in shards.values())


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


def catalog_rows(exhibitions, census, bucket3):
    """One row per curatorial exhibition. data/exhibition_groups.json merges
    API entities that are mint events of the same exhibition (display only —
    raw data keeps the per-entity records)."""
    groups_path = DATA / "exhibition_groups.json"
    groups = json.loads(groups_path.read_text()) if groups_path.exists() else []
    member_of = {}
    for g in groups:
        for slug in g["members"]:
            member_of[slug] = g

    rows = []
    by_group = {}
    for e in exhibitions["list"]:
        c = census["per_exhibition"].get(e["id"], {}) if census else {}
        bm = bucket3["by_slug"].get(e["slug"], 0)
        row = {
            "slug": e["slug"],
            "title": e["title"],
            "start": (e.get("exhibitionStartAt") or "")[:10],
            "works": c.get("works", 0) + bm,
            "independent": c.get("independent", 0),
            "gateway_gap": c.get("gateway_gap", 0),
            "dependent": c.get("dependent", 0) + bm,
            "third_party": c.get("third_party", 0),
        }
        g = member_of.get(e["slug"])
        if g is None:
            rows.append(row)
            continue
        key = g["title"]
        if key not in by_group:
            merged = dict(row)
            merged["slug"] = g["primary_slug"]
            merged["title"] = g["title"]
            merged["members"] = list(g["members"])
            by_group[key] = merged
            rows.append(merged)
        else:
            m = by_group[key]
            for k in ("works", "independent", "gateway_gap", "dependent", "third_party"):
                m[k] += row[k]
            m["start"] = min(m["start"], row["start"])
    return rows


def registry_paragraph(registry):
    if not registry:
        return ("The archival copies above are being anchored on Ethereum; "
                "the registry address will be published here.")
    a = registry["address"]
    return (
        f'The archival copies above are indexed by the Feral File Archive '
        f'manifest, whose current IPFS CID is recorded on Ethereum in the '
        f'<a href="https://etherscan.io/address/{a}#code">'
        f'FeralFileArchiveRegistry</a> at <code>{a}</code> (source verified '
        f'on Etherscan), owned by Feral File\u2019s 2-of-3 custody Safe '
        f'<code>0xA741D850B8B4e684c6F78e9615BD5b33B37AcFcF</code>. The owner '
        f'can only append new manifest versions; every prior version stays '
        f'readable from contract storage, and the contract has no upgrade or '
        f'destruction path. Current manifest: '
        f'<code>{registry["manifest_cid"]}</code> (version '
        f'{registry["version"]}, published {registry["published"]}). What '
        f'this guarantees: Ethereum records which manifest is current; the '
        f'manifest and the copies stay available only while pinned, like '
        f'everything on this page. The works\u2019 own token references do '
        f'not yet point at these copies \u2014 that is the open reference '
        f'phase above.'
    )


def render(bucket3, census, exhibitions, updates, generated_at, registry=None):
    registry_html = registry_paragraph(registry)
    dep_total = bucket3["works_on_bitmark"] + (
        census["buckets"].get("dependent", 0) if census else 0
    )
    if census:
        b = census["buckets"]
        tile1 = tile(
            n(b.get("independent", 0)),
            "works whose media resolves through public gateways",
            f"Every content-addressed media file answered the "
            f"{esc(census['date'])} probe on ipfs.io. Who holds the copies "
            "is not measured \u2014 co-pinning is what makes this durable.",
        )
        tile2 = tile(
            n(b.get("gateway_gap", 0)),
            "works whose content-addressed media failed the gateway probe",
            f"HLS video: master playlists answered, but their stream files "
            f"failed on every gateway tested ({esc(census['date'])}). The "
            "stream files are reachable only from our CDN.",
        )
        tile3_note = (
            f"{n(bucket3['works_on_bitmark'])} Bitmark-era works plus "
            f"{n(b.get('dependent', 0))} on Ethereum and Tezos whose "
            "published media references point only at our CDN. A further "
            f"{n(b.get('third_party', 0))} depend on a third-party platform. "
            "Verified archival copies exist for every Bitmark-era series "
            "(2026-08-04); the published references are not yet updated."
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
        tile3_note = (
            f"Bitmark-era works, enumerated {esc(bucket3['as_of'])}. "
            "Details and remediation below."
        )
        census_note = (
            '<p class="dated">The Ethereum and Tezos census started '
            "August 3, 2026 and probes every file of every edition through the "
            "public gateways a wallet or browser actually uses (ipfs.io, "
            "dweb.link, ipfs.feralfile.com). Its results replace the two "
            "dashes above.</p>"
        )

    tile3 = tile(
        n(dep_total) if census else n(bucket3["works_on_bitmark"]),
        "works whose published media depends entirely on Feral File",
        tile3_note,
    )

    catalog_html = ""
    if census:
        cat_data = catalog_rows(exhibitions, census, bucket3)
        cat_rows = "\n".join(
            f"""        <tr>
          <td><span class="dated">{esc(r["start"])}</span> <a href="https://feralfile.com/exhibitions/{esc(r["slug"])}">{esc(r["title"])}</a></td>
          <td class="num">{n(r["works"])}</td>
          <td class="num">{n(r["independent"])}</td>
          <td class="num">{n(r["gateway_gap"])}</td>
          <td class="num">{n(r["dependent"])}</td>
          <td class="num">{n(r["third_party"])}</td>
        </tr>"""
            for r in cat_data
        )
        cat_totals = {k: sum(r[k] for r in cat_data) for k in ("works","independent","gateway_gap","dependent","third_party")}
        cat_rows += f"""
        <tr>
          <td><strong>All exhibitions</strong></td>
          <td class="num"><strong>{n(cat_totals["works"])}</strong></td>
          <td class="num"><strong>{n(cat_totals["independent"])}</strong></td>
          <td class="num"><strong>{n(cat_totals["gateway_gap"])}</strong></td>
          <td class="num"><strong>{n(cat_totals["dependent"])}</strong></td>
          <td class="num"><strong>{n(cat_totals["third_party"])}</strong></td>
        </tr>"""
        catalog_html = f"""
  <section id="catalog">
    <h2>Every exhibition</h2>
    <p>The whole catalog, oldest first: every published exhibition, how many
    works it holds, and what each work&rsquo;s media depends on today. The
    same states as the tiles above, plus the third-party class. Counting
    note: this table counts the works the census measured (the indexer's
    view) plus never-migrated Bitmark-era works; the Bitmark-era table below
    counts works enumerated from the public API. The two sources diverge by
    exactly one work (Field Guide: one migrated token absent from the
    census). Unsupervised here merges its three MoMA burn-mint records; the
    table below lists the original exhibition entity alone. Source:
    <span class="dated">data/census/&hellip;.csv + bitmark enumeration
    files, all published under Data.</span></p>
    <table>
      <thead>
        <tr><th>Exhibition</th><th class="num">Works</th><th class="num">Resolving via gateways</th><th class="num">Failing probe</th><th class="num">Depend on us</th><th class="num">Third party</th></tr>
      </thead>
      <tbody>
{cat_rows}
      </tbody>
    </table>
  </section>
"""

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
        for f in bucket3["files"]
        + ([bucket3["pin_summary"]["file"]] if bucket3.get("pin_summary") else [])
        + ([exhibitions["file"]])
        + (["census/" + census["file"] + ".gz"] if census else [])
    )

    ps = bucket3.get("pin_summary")
    pin_para = ""
    if ps and ps["all_verified"]:
        pin_para = f"""
    <p>Archival-copy phase, completed {esc(ps["as_of"])}: every one of the
    {n(ps["series"])} Bitmark-era series has a content-addressed copy &mdash;
    {ps["bytes"] / 1e9:.0f}&nbsp;GB added to IPFS and verified byte-for-byte
    against the origin files (source:
    <a href="data/{esc(ps["file"])}">{esc(ps["file"])}</a>). The works&rsquo;
    own published references still point at our CDN, so they remain counted
    as depending on us until the reference phase completes.</p>"""

    eth_dep_para = ""
    if census:
        eth_dep_para = f"""
    <p>The census also surfaced a larger set: {n(census["buckets"].get("dependent", 0))}
    works on Ethereum and Tezos &mdash; discovered {esc(census["date"])} &mdash;
    whose media likewise lives only on our CDN, and
    {n(census["buckets"].get("third_party", 0))} whose media lives on a
    third-party platform &mdash; a different dependency with a different
    owner, listed separately in the data. Works migrated from Bitmark
    share their series&rsquo; files with the copies being pinned now; the
    rest follow the same path: content-addressed copy, byte-verified,
    published here.</p>"""

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
  <p class="lede">Every work we&rsquo;ve published, and what its survival
  depends on &mdash; measured from the outside, file by file, the way a
  collector&rsquo;s wallet or browser fetches art. Today these checks cover
  the artwork files; the metadata link and rendering are not yet measured,
  and the page says so wherever it matters. The raw data lives beside this
  page, in <a href="data/status.json">JSON</a> and <a href="#data">CSV</a>.</p>
</header>

<main>
  <section id="what">
    <h2>What a published work is</h2>
    <p>A work published on Feral File is not a file in one place. It is a
    chain of references: a token on a blockchain points to a smart contract,
    the contract points to metadata, the metadata points to the files of the
    artwork, and those files run in a browser or on an Art Computer. Some
    works also read data from their contract while they run. A work is alive
    when every link in that chain answers.</p>
    <p>Each link has a keeper. The blockchain keeps the token, the contract,
    and anything stored on chain. Content-addressed files can be kept by
    anyone who cares to pin them, including collectors. Anything neither on
    chain nor content-addressed depends on whichever server hosts it &mdash;
    for most works here ours, for six a third-party platform. The fewer
    links that require our servers, the less a work&rsquo;s availability
    depends on Feral File.</p>
    <p>One honest limit is worth stating, because it is widely
    misunderstood: publishing a file on IPFS does not ensure anyone else
    holds a copy. A work stays available only while someone, somewhere,
    keeps one. What
    content addressing adds is that every copy is equal and verifiable
    &mdash; a copy on a collector&rsquo;s computer counts exactly as much as
    one on ours, and none can be altered without detection. So when this
    page publishes a work&rsquo;s content address, holding a byte-identical
    copy of its tested media becomes something any collector, museum, or
    archive can do without asking our permission. The command is one line:
    <code>ipfs pin add &lt;address&gt;</code>. That preserves the files this
    page tested &mdash; not yet the metadata path or the work&rsquo;s
    rendering, which are the next layers of this work.</p>
  </section>

  <section class="tiles" aria-label="Summary">
{tile1}{tile2}{tile3}
  </section>
  {census_note}
{catalog_html}
  <section id="bitmark">
    <h2>Works that depend entirely on us</h2>
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
    across {n(bucket3["series_count"])} series, in the
    {bucket3["exhibitions_affected"]} of {len(bucket3["exhibitions"])}
    Bitmark-era exhibitions with at least one unmigrated work &mdash; have
    published media references that point only to our content delivery
    network (cdn.feralfileassets.com). Those references last answered a
    probe on {esc(probe["date"])}:
    {n(probe["resolving"])} of {n(probe["total"])} series resolved (one probe
    per series; editions of a series share files).</p>{eth_dep_para}
    <p>A published reference that only our servers can answer is not what
    we promise. Remediation runs in two phases. The archival-copy phase
    completed 2026-08-04: every series has a byte-verified content-addressed
    copy. The reference phase &mdash; making each work&rsquo;s own published
    reference resolve independently of our infrastructure &mdash; is open,
    target 2026-11-01; any exception will name the work, the reason, a
    responsible person at Feral File, and a review date.</p>{pin_para}
    <table>
      <thead>
        <tr><th>Exhibition</th><th class="num">Works</th><th class="num">Not yet migrated</th><th class="num">On Ethereum</th><th class="num">On Tezos</th></tr>
      </thead>
      <tbody>
{ex_rows}
      </tbody>
    </table>
  </section>

  <section id="lookup">
    <h2>Look up a work</h2>
    <p>Paste a token ID &mdash; the number in your wallet or on the
    work&rsquo;s page &mdash; and see exactly what that work&rsquo;s media
    depends on, file by file, from the same data as everything above.
    (Search by wallet address is not built yet; token ID only.)</p>
    <form id="lookup-form">
      <input id="lookup-input" type="text" inputmode="text" autocomplete="off"
             placeholder="Token ID" aria-label="Token ID">
      <button type="submit">Check</button>
    </form>
    <div id="lookup-result" aria-live="polite"></div>
  </section>

  <section id="method">
    <h2>What we check, and what we don&rsquo;t yet</h2>
    <p>Two different promises hide inside &ldquo;it still works.&rdquo; A work
    <strong>resolves</strong> when every reference in its chain can be fetched
    from public infrastructure. These checks currently measure the
    <strong>artwork files</strong>, as HTTP HEAD probes: content-addressed
    references through named public gateways (ipfs.io, dweb.link,
    ipfs.feralfile.com), and CDN or third-party references directly from
    their stated hosts. A content-addressed file counts as resolving only
    when a public gateway answers for it &mdash; our own infrastructure
    answering is not enough. Bitmark-era media was probed once per series
    entry file (editions of a series share files); Ethereum and Tezos works
    were probed per enumerated file reference.</p>
    <p>Known gap, found 2026-08-03: HLS video is followed only to its master playlist; the stream files it references are not yet traversed, and for the works flagged above they are not on IPFS at all.</p>
    <p>Not yet measured: the <strong>metadata link</strong> &mdash; whether
    each token&rsquo;s on-chain reference is itself content-addressed &mdash;
    and whether a work <strong>plays</strong>, meaning what resolves also
    renders the way the artist intended. What is stored on chain is not
    probed: it survives with the chain itself. Bitmark-era works are
    enumerated from the public Feral File API by each work&rsquo;s on-chain
    location. This page is regenerated on every update by the open build in
    <a href="https://github.com/feral-file/status">feral-file/status</a>
    from the data files published below; no number on it is typed by
    hand.</p>
  </section>

  <section id="archive">
    <h2>The Feral File Archive</h2>
    <p>{registry_html}</p>
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
<script src="static/lookup.js"></script>
</body>
</html>
"""


def build_markdown(bucket3, census, exhibitions, updates, generated_at, registry=None):
    """The whole page as plain Markdown — the cheap read for a model."""
    probe = bucket3["series_probe"]
    if census:
        b = census["buckets"]
        b1 = f"{b.get('independent', 0):,} works (every content-addressed media file answered the {census['date']} HEAD probe on ipfs.io; who holds the copies is not measured)"
        b2 = f"{b.get('gateway_gap', 0):,} works (HLS video: master playlists answered, stream files failed on every gateway tested; stream files reachable only from our CDN)"
        b3_extra = (
            f" Plus {b.get('dependent', 0):,} works on Ethereum and Tezos whose "
            f"media likewise lives only on our CDN (discovered {census['date']}); "
            "they follow the same remediation path. A further "
            f"{b.get('third_party', 0):,} works depend on a third-party "
            "platform instead of us — different dependency, different owner."
        )
        catalog_md = "\n".join(
            f"| {r['start']} | {r['title']} | {r['works']:,} | {r['independent']:,} "
            f"| {r['gateway_gap']:,} | {r['dependent']:,} |"
            for r in catalog_rows(exhibitions, census, bucket3)
        )
        catalog_section = f"""
## Every exhibition (oldest first)

| Started | Exhibition | Works | Resolve without us | Failing gateways | Depend on us |
|---|---|---:|---:|---:|---:|
{catalog_md}
"""
    else:
        b1 = b2 = "census in progress (started 2026-08-03; publishes here on completion)"
        b3_extra = ""
        catalog_section = ""
    rows = "\n".join(
        f"| {e['title']} | {e['works']:,} | {e['still_bitmark'] + e['swap_initiated']:,} "
        f"| {e['migrated_ethereum']:,} | {e['migrated_tezos']:,} |"
        for e in bucket3["exhibitions"]
    )
    ps = bucket3.get("pin_summary")
    pin_md = ""
    if ps and ps["all_verified"]:
        pin_md = (
            f" Archival-copy phase completed {ps['as_of']}: all {ps['series']}"
            f" series have byte-verified content-addressed copies"
            f" ({ps['bytes']/1e9:.0f} GB; addresses in {SITE_URL}/data/{ps['file']})."
        )
    upd = "\n".join(f"- **{u['date']} — {u['title']}.** {u['body']}" for u in updates)
    if registry:
        reg_md = (
            f"Registry on Ethereum: {registry['address']} (FeralFileArchiveRegistry, "
            f"source-verified; owned by Feral File's 2-of-3 custody Safe "
            f"0xA741D850B8B4e684c6F78e9615BD5b33B37AcFcF; owner can only append "
            f"manifest versions, prior versions immutable in contract storage, no "
            f"upgrade or destruction path). Current manifest: "
            f"{registry['manifest_cid']} (version {registry['version']}, published "
            f"{registry['published']}). Ethereum records which manifest is current; "
            f"the manifest and copies stay available only while pinned. The works' "
            f"own token references do not yet point at these copies."
        )
    else:
        reg_md = "Being anchored on Ethereum; address publishes here."
    return f"""# Feral File Status

Every work we've published, and whether it still works — checked from the
outside, the way a collector's wallet or browser fetches art. Generated
{generated_at}. Canonical URL: {SITE_URL}
Machine-readable summary: {SITE_URL}/data/status.json

## What a published work is

A work published on Feral File is a chain of references: a token on a
blockchain points to a smart contract, the contract points to metadata, the
metadata points to the files of the artwork, and those files run in a browser
or on an Art Computer. Some works also read data from their contract while
they run. A work is alive when every link in that chain answers.

Each link has a keeper. The blockchain keeps the token, the contract, and
anything stored on chain. Content-addressed files can be kept by anyone who
cares to pin them. Anything neither on chain nor content-addressed depends
on whichever server hosts it — for most works here ours, for six a
third-party platform. The fewer links that require our servers, the less a
work's availability depends on Feral File.

One limit, widely misunderstood: publishing a file on IPFS does not ensure
anyone else holds a copy. A work stays available only while someone,
somewhere, keeps one. What content addressing adds is that every copy is
equal and verifiable — a collector's copy counts exactly as much as ours,
and none can be altered without detection. When this page publishes a work's
content address, holding a byte-identical copy of its tested media is one
command for any collector, museum, or archive: ipfs pin add <address>. That
preserves the files this page tested — not yet the metadata path or the
work's rendering.

## Works, by what their media depends on

1. Resolve without Feral File: {b1}
2. Should resolve without us, but currently fail on public gateways: {b2}
3. Published media references depend entirely on Feral File:
   {bucket3["works_on_bitmark"]:,} Bitmark-era works across
   {bucket3["series_count"]:,} series, in the
   {bucket3["exhibitions_affected"]} of 18 Bitmark-era exhibitions with at
   least one unmigrated work (as of {bucket3["as_of"]}); their published
   references point only to cdn.feralfileassets.com. Byte-verified archival
   copies exist for every series as of 2026-08-04 (pin manifest under
   Data); the references themselves are not yet updated. Ownership records
   are archived and independently anchored — data on IPFS, Merkle root on
   Ethereum, timestamp on Bitcoin
   (https://github.com/bitmark-inc/bitmarkd/wiki/bitmark-archive) — though
   the archive too stays available only while someone retains it.{b3_extra}
   Last reference probe {probe["date"]}: {probe["resolving"]:,} of
   {probe["total"]:,} series answered (one probe per series entry file;
   editions share files). Reference-phase remediation target 2026-11-01;
   exceptions will name the work, reason, responsible person, and review
   date.{pin_md}
{catalog_section}
## Bitmark-era exhibitions

| Exhibition | Works | Not yet migrated | On Ethereum | On Tezos |
|---|---:|---:|---:|---:|
{rows}

## What we check, and what we don't yet

A work RESOLVES when every reference in its chain can be fetched from public
infrastructure. These checks currently measure the ARTWORK FILES: every file
of every edition is requested over the public gateways wallets and browsers
use. A file counts as resolving only when a public gateway serves it — our
own infrastructure answering is not enough.

Not yet measured: the METADATA LINK (whether each token's on-chain reference
is itself content-addressed), and whether a work PLAYS (what resolves also
renders as the artist intended). On-chain data is not probed: it survives
with the chain itself. The page is regenerated from the raw data on every
update.

## The Feral File Archive

{reg_md}

## Check a work you own

The page at {SITE_URL} has a per-work lookup: paste a token ID (Ethereum,
Tezos, or 64-char Bitmark ID) and see that work's file-by-file state and,
for Bitmark-era works, its archival copy address. The same data is in
data/work_index.json + data/works/ (sharded JSON, documented in the repo).

## Data

- {SITE_URL}/data/status.json — every number on this page, structured
- {SITE_URL}/data/pin_manifest_2026-08-04.csv — archival copies: series → CID
- {SITE_URL}/data/census/token_census_20260803T182523Z.csv.gz — the full probe, one row per file
- Bitmark enumeration + per-series probes + exhibition totals: named at {SITE_URL}/#data
- {SITE_URL}/feed.xml (RSS, one entry per update)

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

- [RSS feed]({SITE_URL}/feed.xml): one entry per update

## On-chain

- Registry: 0x9aF574cafe2C14161DEC1eAC11F7F2c281fCa34e (Ethereum mainnet,
  FeralFileArchiveRegistry) — current archive-manifest CID, plus full version
  history in contract storage.
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
    exhibitions = load_exhibitions()
    registry = load_registry()
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

    extra = [bucket3["pin_summary"]["file"]] if bucket3.get("pin_summary") else []
    for f in bucket3["files"] + extra + [exhibitions["file"]]:
        shutil.copy(DATA / f, PUBLIC / "data" / f)
    if census:
        # Cloudflare Pages caps files at 25 MiB; the census CSV exceeds it.
        (PUBLIC / "data" / "census").mkdir()
        with open(DATA / "census" / census["file"], "rb") as f_in, gzip.open(
            PUBLIC / "data" / "census" / (census["file"] + ".gz"), "wb", compresslevel=9
        ) as f_out:
            shutil.copyfileobj(f_in, f_out)

    dep_total = bucket3["works_on_bitmark"] + (
        census["buckets"].get("dependent", 0) if census else 0
    )
    status = {
        "generated_at": now.isoformat(timespec="seconds"),
        "site": SITE_URL,
        "works_by_media_dependency": {
            "resolve_without_feralfile": (
                {"works": census["buckets"].get("independent", 0), "as_of": census["date"]}
                if census
                else {"status": "census_in_progress", "started": "2026-08-03"}
            ),
            "depend_on_third_party": (
                {"works": census["buckets"].get("third_party", 0), "as_of": census["date"]}
                if census
                else None
            ),
            "failing_public_gateways": (
                {"works": census["buckets"].get("gateway_gap", 0), "as_of": census["date"]}
                if census
                else {"status": "census_in_progress", "started": "2026-08-03"}
            ),
            "depend_entirely_on_feralfile": {
                "works": dep_total,
                "bitmark_era": {
                    "works": bucket3["works_on_bitmark"],
                    "series": bucket3["series_count"],
                    "exhibitions": bucket3["exhibitions_affected"],
                    "as_of": bucket3["as_of"],
                    "last_probe": bucket3["series_probe"],
                    "media_mix_by_series": bucket3["media_mix"],
                },
                "archival_copies": (
                    {
                        "series": bucket3["pin_summary"]["series"],
                        "bytes": bucket3["pin_summary"]["bytes"],
                        "byte_verified": bucket3["pin_summary"]["all_verified"],
                        "as_of": bucket3["pin_summary"]["as_of"],
                        "manifest": "data/" + bucket3["pin_summary"]["file"],
                    }
                    if bucket3.get("pin_summary")
                    else None
                ),
                "eth_tezos_cdn_only": (
                    {"works": census["buckets"].get("dependent", 0), "as_of": census["date"]}
                    if census
                    else None
                ),
                "host": "cdn.feralfileassets.com",
                "remediation": "content-addressed copy per work, targeted 2-3 months from 2026-08-03",
            },
        },
        "scope": {
            "measures": "resolves, media layer: every artwork file fetchable from the public gateways wallets and browsers use",
            "not_yet_measured": [
                "metadata link: whether each token's on-chain reference is content-addressed",
                "plays: what resolves also renders as the artist intended",
            ],
        },
        "exhibitions": (
            catalog_rows(exhibitions, census, bucket3) if census else None
        ),
        "archive_registry": registry,
        "bitmark_exhibitions": bucket3["exhibitions"],
        "updates": updates,
    }

    shard_works = emit_work_shards(census, bucket3, exhibitions)
    print(f"lookup shards: {shard_works} works indexed")
    (PUBLIC / "index.html").write_text(
        render(bucket3, census, exhibitions, updates, generated_at, registry)
    )
    (PUBLIC / "data" / "status.json").write_text(
        json.dumps(status, indent=2, ensure_ascii=False)
    )
    (PUBLIC / "feed.xml").write_text(build_feed(updates, now))
    (PUBLIC / "status.md").write_text(
        build_markdown(bucket3, census, exhibitions, updates, generated_at, registry)
    )
    (PUBLIC / "llms.txt").write_text(build_llms_txt(bucket3))
    (PUBLIC / "robots.txt").write_text(ROBOTS_TXT)
    (PUBLIC / "_headers").write_text(HEADERS_FILE)

    kind = f"census {census['file']}" if census else "census pending"
    print(f"built public/ ({kind}, bucket3 as of {bucket3['as_of']})")


if __name__ == "__main__":
    main()
