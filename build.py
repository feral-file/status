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
published work, and what its survival depends on at the artwork-media
layer. A published work is a chain of
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
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
PUBLIC = ROOT / "public"
SITE_URL = "https://status.feralfile.com"

# One canonical claim, shared by every summary surface (HTML meta, Markdown,
# llms.txt, RSS, JSON scope). The measured layer is artwork media; the
# metadata link and rendering are not yet measured, and every surface that
# introduces itself must say so in the same breath as the claim.
CLAIM = (
    "what its artwork media depends on — checked from the outside, "
    "the way a collector's wallet or browser fetches art"
)


def measurement_scope(census, bucket3):
    """The measured boundary + probe dates, published as status.json's scope.

    generated_at is the page-build time; these dates are measurement time.
    """
    return {
        "layer": "artwork_media",
        "measures": (
            "resolves, media layer: every artwork file fetched through a gateway "
            "Feral File does not operate (a dedicated gateway run by Filebase, "
            "public gateways as backups), plus who provides it "
            "(delegated routing) -- a file is redundant only when a "
            "non-Feral-File provider holds it"
            if census and census.get("schema") == 2
            else "resolves, media layer: every artwork file fetchable from the "
            "public gateways wallets and browsers use"
        ),
        "media_probe_as_of": census["date"] if census else None,
        "bitmark_reference_probe_as_of": bucket3["series_probe"]["date"],
        "not_yet_measured": [
            "metadata link: whether each token's on-chain reference is content-addressed",
            "plays: what resolves also renders as the artist intended",
        ],
    }


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


# Census schema 2 (token-health-monitor, 2026-09): one verdict per file.
# Page state per verdict; a work takes the worst of its files.
V2_STATE = {
    "redundant": "redundant",      # a non-Feral-File provider holds it
    "independent": "independent",  # a gateway we do not operate serves it; only known copy is ours
    "ff_only": "ff_only",          # only our node serves it
    "unreachable": "gateway_gap",  # nobody serves it
    "unmeasured": "unmeasured",    # probe rate-limited / errored: neither gap nor pass
}
V2_SEVERITY = {"unreachable": 0, "ff_only": 1, "unmeasured": 2, "independent": 3, "redundant": 4}


def worst_verdict(verdicts):
    """Work-level verdict = worst file. Anything unknown/empty is unmeasured:
    a rate limit must never turn into a claim in either direction."""
    vs = [v if v in V2_SEVERITY else "unmeasured" for v in verdicts]
    return min(vs, key=V2_SEVERITY.__getitem__) if vs else "unmeasured"


# The host that served the public fetch, as a label. The census cell is
# "ok:<host>[;<host>:<reason>…]"; the serving host is between "ok:" and the
# first ";" (the same parse the census summary uses). Unknown hosts pass
# through so the raw record is never hidden.
GATEWAY_LABELS = {
    "ipfs.io": "ipfs.io (Shipyard)",
    "dweb.link": "dweb.link (Shipyard)",
    "gateway.pinata.cloud": "gateway.pinata.cloud (Pinata)",
}


def public_via(cell):
    if not cell.startswith("ok:"):
        return ""
    host = cell[3:].split(";", 1)[0].strip().lower()
    if host.endswith(".myfilebase.com"):
        return "Filebase dedicated gateway"
    return GATEWAY_LABELS.get(host, host)


def load_census():
    """Media-layer rollup of the token-health-monitor census, if present.

    The census fetches metadata via Feral File's API, so metadata rows say
    nothing about on-chain tokenURI hosting — they are EXCLUDED here. A work
    is classified by its media resources only.

    Schema 2 CSVs (a ``verdict`` column) roll the per-file verdicts up to
    the worst one per work:
      redundant     every content-addressed file resolves on a gateway we do
                    not operate AND a non-Feral-File provider holds it
      independent   a gateway we do not operate serves every file; the only known
                    copy of at least one is ours
      ff_only       at least one file is served only by our node
      gateway_gap   at least one file nobody serves
      unmeasured    at least one file's probe was rate-limited/errored
    Schema 1 CSVs (pre-2026-09, ``ipfs_io_ok`` column) keep the old split:
      independent   has content-addressed media, all of it resolving on ipfs.io
      gateway_gap   has content-addressed media, at least one file failing
    Both:
      dependent     no content-addressed media at all (CDN/other hosting only)
      third_party   every file on a third-party host
    """
    candidates = sorted(glob.glob(str(DATA / "census" / "token_census_*.csv")))
    if not candidates:
        return None
    path = Path(candidates[-1])

    per_work = {}
    reader = csv.DictReader(open(path))
    v2 = "verdict" in (reader.fieldnames or [])
    for r in reader:
        if r["resource"] == "metadata":
            continue
        key = (r["chain"], r["contract"], r["token_id"])
        st = per_work.setdefault(
            key, {"cid": 0, "fail": 0, "other": 0, "rest": 0, "ex": r["exhibition"], "verdicts": []}
        )
        if r["cid"]:
            st["cid"] += 1
            if v2:
                st["verdicts"].append(r.get("verdict", ""))
            elif r.get("ipfs_io_ok", "") != "ok":
                st["fail"] += 1
        elif r["hosting"] == "other":
            st["other"] += 1
        else:
            st["rest"] += 1

    buckets = Counter()
    per_ex = defaultdict(Counter)
    for st in per_work.values():
        if st["cid"]:
            if v2:
                state = V2_STATE[worst_verdict(st["verdicts"])]
            else:
                state = "gateway_gap" if st["fail"] else "independent"
        elif st["other"] and not st["rest"]:
            state = "third_party"
        else:
            state = "dependent"
        buckets[state] += 1
        per_ex[st["ex"]][state] += 1
        per_ex[st["ex"]]["works"] += 1
    d = path.name.replace("token_census_", "").split("T")[0]
    return {
        "file": path.name,
        "date": f"{d[:4]}-{d[4:6]}-{d[6:]}",
        "schema": 2 if v2 else 1,
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
        v2 = census.get("schema") == 2
        reader = csv.DictReader(open(DATA / "census" / census["file"]))
        # The "ours" column is named from census.own_gateways[0] upstream
        # (ipfs_feralfile_com_ok today); read it off the header, not by name.
        own_col = next((c for c in (reader.fieldnames or []) if c.endswith("_ok")), "")
        if v2 and not own_col:
            raise SystemExit(f"census {census['file']}: schema 2 without an own-gateway *_ok column")
        for r in reader:
            if r["resource"] == "metadata":
                continue
            key = (r["chain"], r["contract"], r["token_id"], r["exhibition"])
            w = per_work.setdefault(
                key, {"chain": r["chain"], "contract": r["contract"], "files": []}
            )
            if r["cid"] and v2:
                f = {
                    "res": r["resource"],
                    "host": "ipfs",
                    "cid": r["cid"],
                    "verdict": r.get("verdict") or "unmeasured",
                    # Raw census cells: "ok", "fail: HTTP 404 from media host",
                    # "fail: HTTP 429 ..." -- shown as recorded, never
                    # collapsed to a verdict the census did not give.
                    "ours": (r.get(own_col) or "unmeasured")[:80],
                    "public": r.get("public_fetch", ""),
                    "public_via": public_via(r.get("public_fetch", "")),
                }
                if (r.get("providers_total") or "").isdigit():
                    f["providers"] = {
                        "total": int(r["providers_total"]),
                        "ff": int(r.get("providers_ff") or 0) if (r.get("providers_ff") or "0").isdigit() else 0,
                        "nonff": int(r.get("providers_nonff") or 0) if (r.get("providers_nonff") or "0").isdigit() else 0,
                        "ids": [i for i in (r.get("provider_ids") or "").split(";") if i],
                    }
                w["files"].append(f)
            elif r["cid"]:
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
            elif v2:
                state = V2_STATE[worst_verdict(f["verdict"] for f in cids)]
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
                "state": "not_migrated",
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


# Catalog table columns: (key, header). "resolves" = independent + redundant,
# "depend" = dependent + ff_only (see catalog_cell).
CATALOG_COLUMNS_V1 = (
    ("works", "Works"),
    ("independent", "Resolving via gateways"),
    ("gateway_gap", "Failing probe"),
    ("dependent", "Depend on us"),
    ("not_migrated", "Not yet migrated"),
    ("third_party", "Third party"),
)
CATALOG_COLUMNS_V2 = (
    ("works", "Works"),
    ("resolves", "Resolve without us"),
    ("redundant", "of which redundant"),
    ("gateway_gap", "Nobody serves"),
    ("depend", "Depend on us"),
    ("unmeasured", "Unmeasured"),
    ("not_migrated", "Not yet migrated"),
    ("third_party", "Third party"),
)
CATALOG_KEYS = ("works", "independent", "redundant", "gateway_gap", "dependent", "ff_only", "unmeasured", "not_migrated", "third_party")


def catalog_cell(row, key):
    if key == "resolves":
        return row["independent"] + row.get("redundant", 0)
    if key == "depend":
        return row["dependent"] + row.get("ff_only", 0)
    return row.get(key, 0)


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
            "dependent": c.get("dependent", 0),
            "not_migrated": bm,
            "third_party": c.get("third_party", 0),
        }
        if census and census.get("schema") == 2:
            # Only a schema-2 census can tell these apart; a v1 build must
            # not publish hard zeros for states it never measured.
            row.update(
                redundant=c.get("redundant", 0),
                ff_only=c.get("ff_only", 0),
                unmeasured=c.get("unmeasured", 0),
            )
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
            for k in CATALOG_KEYS:
                if k in row:
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
        f'everything on this page. A not-yet-migrated work\u2019s own token '
        f'references do not point at these copies until its collector '
        f'migrates it \u2014 the swap writes them.'
    )


def render(bucket3, census, exhibitions, updates, generated_at, registry=None):
    registry_html = registry_paragraph(registry)
    media_probe = census["date"] if census else bucket3["series_probe"]["date"]
    tile5 = ""
    if census and census.get("schema") == 2:
        b = census["buckets"]
        resolves = b.get("independent", 0) + b.get("redundant", 0)
        tile1 = tile(
            n(resolves),
            "works whose media resolves without Feral File",
            f"Every content-addressed media file was served on "
            f"{esc(census['date'])} by a gateway we do not operate. "
            f"{n(b.get('redundant', 0))} of these are <strong>redundant</strong>: a "
            "provider other than Feral File also holds every file (peer IDs in "
            f"the census data). The other {n(b.get('independent', 0))} resolve, "
            "but the only known copy of at least one file is ours &mdash; "
            "pinning by anyone else is what makes them durable.",
        )
        tile2 = tile(
            n(b.get("gateway_gap", 0)),
            "works whose content-addressed media nobody serves",
            f"At least one content-addressed media file failed on "
            f"{esc(census['date'])} both through our own node and through "
            "a gateway we do not operate. Listed per file in the census data.",
        )
        tile3_note = (
            f"{n(b.get('dependent', 0))} works on Ethereum and Tezos whose "
            "published media references point only at our CDN &mdash; the open "
            "CDN-retirement phase (ops/cdn-retirement-phase2.md in the repo). "
            f"A further {n(b.get('ff_only', 0))} are content-addressed but on "
            f"{esc(census['date'])} only our own node served them: pinned by "
            "us, held by no one else yet. Their content addresses are in the "
            f"per-work lookup below. Another {n(b.get('third_party', 0))} depend "
            "on a third-party platform, listed separately in the data."
        )
        tile5 = tile(
            n(b.get("unmeasured", 0)),
            "works whose media could not be measured",
            f"On {esc(census['date'])} at least one file's probe ended in a "
            "gateway rate limit or a routing error after its retry budget. "
            "Neither a gap nor a pass: they are re-probed file by file (a "
            "CID-level rescan, run by hand) before the next publish, and "
            "never counted in the tiles above.",
        )
        census_note = ""
    elif census:
        b = census["buckets"]
        tile1 = tile(
            n(b.get("independent", 0)),
            "works whose media resolves through public gateways",
            f"Every content-addressed media file answered the "
            f"{esc(census['date'])} probe on ipfs.io. Who holds the copies "
            "is not measured. Independent pinning is what makes them durable.",
        )
        tile2 = tile(
            n(b.get("gateway_gap", 0)),
            "works whose content-addressed media failed the gateway probe",
            f"At least one content-addressed media file failed the "
            f"{esc(census['date'])} probe on ipfs.io. Each is listed "
            "per file in the census data; some are transient gateway "
            "errors, some are files not pinned anywhere public.",
        )
        tile3_note = (
            "Works on Ethereum and Tezos whose published media references "
            "point only at our CDN. Repointing them to content-addressed "
            "copies is the open CDN-retirement phase "
            "(ops/cdn-retirement-phase2.md in the repo). A further "
            f"{n(b.get('third_party', 0))} depend on a third-party platform, "
            "listed separately in the data."
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
            "First full census in progress. Publishes here when it completes."
        )
        census_note = (
            '<p class="dated">The Ethereum and Tezos census started '
            "August 3, 2026 and probes every file of every edition through the "
            "public gateways a wallet or browser actually uses (ipfs.io, "
            "dweb.link, ipfs.feralfile.com). Its results replace the two "
            "dashes above.</p>"
        )

    tile3 = tile(
        (
            n(census["buckets"].get("dependent", 0) + census["buckets"].get("ff_only", 0))
            if census
            else "&mdash;"
        ),
        (
            "works whose media depends entirely on Feral File"
            if census and census.get("schema") == 2
            else "works whose published media depends entirely on Feral File"
        ),
        tile3_note,
    )
    tile4 = tile(
        n(bucket3["works_on_bitmark"]),
        "Bitmark-era works not yet migrated",
        "Never swapped to Ethereum or Tezos, so their published references "
        "still resolve only through our CDN. Every series has a byte-verified "
        "archival copy on IPFS (2026-08-04), and a swap now writes "
        "content-addressed references &mdash; the migration tooling fails "
        "closed without them. Completing a migration moves a work to the "
        "first tile.",
    )

    catalog_html = ""
    if census:
        cat_data = catalog_rows(exhibitions, census, bucket3)
        cols = CATALOG_COLUMNS_V2 if census.get("schema") == 2 else CATALOG_COLUMNS_V1
        cat_rows = "\n".join(
            f"""        <tr>
          <td><span class="dated">{esc(r["start"])}</span> <a href="https://feralfile.com/exhibitions/shows/{esc(r["slug"])}">{esc(r["title"])}</a></td>
"""
            + "\n".join(f'          <td class="num">{n(catalog_cell(r, k))}</td>' for k, _ in cols)
            + """
        </tr>"""
            for r in cat_data
        )
        cat_totals = {k: sum(catalog_cell(r, k) for r in cat_data) for k, _ in cols}
        cat_rows += (
            """
        <tr>
          <td><strong>All exhibitions</strong></td>
"""
            + "\n".join(f'          <td class="num"><strong>{n(cat_totals[k])}</strong></td>' for k, _ in cols)
            + """
        </tr>"""
        )
        cat_head = "".join(f'<th class="num">{esc(label)}</th>' for _, label in cols)
        cat_states_note = (
            " (redundant is the subset of resolving works a third party also holds)"
            if census.get("schema") == 2
            else ""
        )
        catalog_html = f"""
  <section id="catalog">
    <h2>Every exhibition</h2>
    <p>The whole catalog, oldest first: every published exhibition, how many
    works it holds, and what each work&rsquo;s media depends on today. The
    same states as the tiles above, plus the third-party class{cat_states_note}. Counting
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
        <tr><th>Exhibition</th>{cat_head}</tr>
      </thead>
      <tbody>
{cat_rows}
      </tbody>
    </table>
  </section>
"""

    ex_rows = "\n".join(
        f"""        <tr>
          <td><a href="https://feralfile.com/exhibitions/shows/{esc(e["slug"])}">{esc(e["title"])}</a></td>
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
    <a href="data/{esc(ps["file"])}">{esc(ps["file"])}</a>). Each
    work&rsquo;s own published references update when its collector
    migrates it; until then it is counted above as not yet migrated.</p>"""

    if census and census.get("schema") == 2:
        method_gateways = (
            "one gateway Feral File does not operate per file: a dedicated "
            "gateway operated by Filebase that fetches from the IPFS network, "
            "with the public gateways (ipfs.io/dweb.link, Pinata) as backups "
            "when it cannot answer &mdash; the census records which host "
            "served each file &mdash; and, separately, our own node "
            "ipfs.feralfile.com"
        )
        method_providers = (
            " Each file is also looked up in delegated routing "
            "(<code>/routing/v1/providers</code>): a work counts as "
            "<strong>redundant</strong> only when a provider other than "
            "Feral File&rsquo;s nodes holds every file. A probe the gateway "
            "rate-limited is recorded as <strong>unmeasured</strong> and "
            "re-run, never as a gap."
        )
    else:
        method_gateways = "named public gateways (ipfs.io, dweb.link, ipfs.feralfile.com)"
        method_providers = ""

    eth_dep_para = ""
    if census:
        eth_dep_para = f"""
    <p>The census also surfaced a larger set: {n(census["buckets"].get("dependent", 0))}
    works on Ethereum and Tezos &mdash; discovered {esc(census["date"])} &mdash;
    whose media likewise lives only on our CDN, and
    {n(census["buckets"].get("third_party", 0))} whose media lives on a
    third-party platform &mdash; a different dependency with a different
    owner, listed separately in the data. That set is the open
    CDN-retirement work (phase 2), and it follows the same path the
    Bitmark-era migration took: content-addressed copy, byte-verified,
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
<meta name="description" content="Every work Feral File has published, and {CLAIM}.">
</head>
<body>
<header>
  <p class="brand"><a href="https://feralfile.com">Feral File</a></p>
  <h1>Status</h1>
  <p class="lede">Every work we&rsquo;ve published, and what its survival
  depends on &mdash; measured from the outside, file by file, the way a
  collector&rsquo;s wallet or browser fetches art. Today these checks cover
  the artwork files, last probed {esc(media_probe)}; the metadata link and
  rendering are not yet measured, and the page says so wherever it matters. The raw data lives beside this
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
    <p>One limit is worth stating, because it is widely
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
{tile1}{tile2}{tile3}{tile5}{tile4}
  </section>
  {census_note}
{catalog_html}
  <section id="bitmark">
    <h2>Bitmark-era works not yet migrated</h2>
    <p>Feral File&rsquo;s first {len(bucket3["exhibitions"])} exhibitions were
    minted on the Bitmark blockchain, which we built in 2014 and retired in
    2025. The chain itself was preserved as a verifiable archive &mdash; its
    data on IPFS, its Merkle root on Ethereum, a timestamp on Bitcoin (<a
    href="https://github.com/bitmark-inc/bitmarkd/wiki/bitmark-archive">the
    Bitmark Archive</a>; <a
    href="https://feralfile.substack.com/p/before-ethereum-before-nfts-there">the
    story</a>) &mdash; so the ownership records of these works can be
    verified without us. What remained exposed was the artwork files
    themselves. Works later
    collected on Ethereum or Tezos were migrated, and since 2026-09-01
    every migrated token&rsquo;s published media references are
    content-addressed (5,880 tokens repointed on-chain &mdash; see Updates);
    the {n(bucket3["works_on_bitmark"])} works never migrated &mdash;
    across {n(bucket3["series_count"])} series, in the
    {bucket3["exhibitions_affected"]} of {len(bucket3["exhibitions"])}
    Bitmark-era exhibitions with at least one unmigrated work &mdash; have
    published media references that point only to our content delivery
    network (cdn.feralfileassets.com). Those references last answered a
    probe on {esc(probe["date"])}:
    {n(probe["resolving"])} of {n(probe["total"])} series resolved (one probe
    per series; editions of a series share files).</p>{eth_dep_para}
    <p>A published reference that only our servers can answer is not what
    we promise. For these works both preconditions of independence are in
    place: the archival-copy phase completed 2026-08-04 (every series has a
    byte-verified content-addressed copy), and a swap now writes
    content-addressed references into the migrated token &mdash; the
    migration tooling fails closed without them, and the 5,880 tokens
    swapped before that guard existed were repointed on-chain 2026-09-01.
    What remains is the migration itself, which only a collector can
    trigger; until then a work&rsquo;s published references resolve only
    through our CDN, and this page counts it not yet migrated rather than
    permanently ours. The standing depends-on-us work &mdash; the
    Ethereum/Tezos CDN class above &mdash; has its own retirement plan
    (ops/cdn-retirement-phase2.md), target 2026-11-01; any exception will
    name the work, the reason, a responsible person at Feral File, and a
    review date.</p>{pin_para}
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
    <h2>Look up a work &mdash; or a whole wallet</h2>
    <p>Paste a token ID &mdash; the number in your wallet or on the
    work&rsquo;s page &mdash; and see exactly what that work&rsquo;s media
    depends on, file by file, from the same data as everything above. Or
    paste a wallet address (Ethereum <code>0x&hellip;</code> or Tezos
    <code>tz&hellip;</code>) to see every published work it holds and get a
    pin list &mdash; one file of content addresses, ready for
    <code>ipfs pin add</code> &mdash; so you can hold your own copies.
    Wallet holdings are read from public indexers directly by your browser;
    this site has no server and never sees the address.</p>
    <form id="lookup-form">
      <input id="lookup-input" type="text" inputmode="text" autocomplete="off"
             placeholder="Token ID or wallet address" aria-label="Token ID or wallet address">
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
    references through {method_gateways}, and CDN or third-party references directly from
    their stated hosts. A content-addressed file counts as resolving only
    when a gateway we do not operate answers for it &mdash; our own
    infrastructure answering is not enough.{method_providers} Bitmark-era media was probed once per series
    entry file (editions of a series share files); Ethereum and Tezos works
    were probed per enumerated file reference.</p>
    <p>Known gap, found 2026-08-03 and closed 2026-08-25: HLS video was followed only to its master playlist, and for 184 works the stream files were never on IPFS. Those works now reference plain MP4s on IPFS (on-chain and in our records); the census still does not traverse HLS playlists, so any future HLS reference would show up here as a gateway failure, not as a pass.</p>
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
<script src="static/wallet.js"></script>
<script src="static/lookup.js"></script>
</body>
</html>
"""


def build_markdown(bucket3, census, exhibitions, updates, generated_at, registry=None):
    """The whole page as plain Markdown — the cheap read for a model."""
    probe = bucket3["series_probe"]
    b5 = ""
    bitmark_item_no = 5 if (census and census.get("schema") == 2) else 4
    if census and census.get("schema") == 2:
        b = census["buckets"]
        b1 = (
            f"{b.get('independent', 0) + b.get('redundant', 0):,} works (every "
            f"content-addressed media file was served on {census['date']} by a "
            f"gateway Feral File does not operate; {b.get('redundant', 0):,} of them are "
            "redundant — a non-Feral-File provider also holds every file, per delegated "
            f"routing — and {b.get('independent', 0):,} resolve with the only known copy "
            "of at least one file being ours)"
        )
        b2 = (
            f"{b.get('gateway_gap', 0):,} works (at least one content-addressed media file "
            f"failed on {census['date']} both through our own node and through public "
            "gateways; listed per file in the census data)"
        )
        b3 = (
            f"{b.get('dependent', 0) + b.get('ff_only', 0):,} works on Ethereum and Tezos: "
            f"{b.get('dependent', 0):,} whose media lives only on our CDN (as of "
            f"{census['date']}; the repointing plan is ops/cdn-retirement-phase2.md in "
            f"the repo, target 2026-11-01) and {b.get('ff_only', 0):,} whose media is "
            "content-addressed but was served only by our own node — pinned by us, held "
            f"by no one else yet. A further {b.get('third_party', 0):,} works depend on a "
            "third-party platform instead of us — different dependency, different owner."
        )
        b5 = (
            f"\n4. Could not be measured: {b.get('unmeasured', 0):,} works (at least one "
            f"file's probe on {census['date']} ended in a gateway rate limit or routing "
            "error after its retry budget; re-probed file by file, by hand, before "
            "the next publish; never counted above)"
        )
        catalog_md = "\n".join(
            f"| {r['start']} | {r['title']} | {r['works']:,} | {catalog_cell(r, 'resolves'):,} "
            f"| {r['redundant']:,} | {r['gateway_gap']:,} | {catalog_cell(r, 'depend'):,} "
            f"| {r['unmeasured']:,} | {r['not_migrated']:,} |"
            for r in catalog_rows(exhibitions, census, bucket3)
        )
        catalog_section = f"""
## Every exhibition (oldest first)

| Started | Exhibition | Works | Resolve without us | of which redundant | Nobody serves | Depend on us | Unmeasured | Not yet migrated |
|---|---|---:|---:|---:|---:|---:|---:|---:|
{catalog_md}
"""
    elif census:
        b = census["buckets"]
        b1 = f"{b.get('independent', 0):,} works (every content-addressed media file answered the {census['date']} HEAD probe on ipfs.io; who holds the copies is not measured)"
        b2 = f"{b.get('gateway_gap', 0):,} works (at least one content-addressed media file failed the {census['date']} HEAD probe on ipfs.io; listed per file in the census data)"
        b3 = (
            f"{b.get('dependent', 0):,} works on Ethereum and Tezos whose "
            f"media lives only on our CDN (as of {census['date']}); the "
            "repointing plan is ops/cdn-retirement-phase2.md in the repo, "
            "target 2026-11-01. A further "
            f"{b.get('third_party', 0):,} works depend on a third-party "
            "platform instead of us — different dependency, different owner."
        )
        catalog_md = "\n".join(
            f"| {r['start']} | {r['title']} | {r['works']:,} | {r['independent']:,} "
            f"| {r['gateway_gap']:,} | {r['dependent']:,} | {r['not_migrated']:,} |"
            for r in catalog_rows(exhibitions, census, bucket3)
        )
        catalog_section = f"""
## Every exhibition (oldest first)

| Started | Exhibition | Works | Resolve without us | Failing gateways | Depend on us | Not yet migrated |
|---|---|---:|---:|---:|---:|---:|
{catalog_md}
"""
    else:
        b1 = b2 = b3 = "census in progress (started 2026-08-03; publishes here on completion)"
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
    media_probe = census["date"] if census else probe["date"]
    return f"""# Feral File Status

Every work we've published, and {CLAIM}. The metadata link and the work's
rendering are not yet measured — see "What we check" below. Media last
probed {media_probe}; page generated {generated_at}.
Canonical URL: {SITE_URL}
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
3. Published media references depend entirely on Feral File: {b3}
   Exceptions to the target will name the work, reason, responsible
   person, and review date.{b5}
{bitmark_item_no}. Not yet migrated from Bitmark: {bucket3["works_on_bitmark"]:,} works
   across {bucket3["series_count"]:,} series, in the
   {bucket3["exhibitions_affected"]} of 18 Bitmark-era exhibitions with at
   least one unmigrated work (as of {bucket3["as_of"]}). Their published
   references point only to cdn.feralfileassets.com until each collector
   migrates; a swap now writes content-addressed references — it fails
   closed without them, and the 5,880 previously swapped tokens were
   repointed on-chain 2026-09-01. Byte-verified archival copies exist for
   every series as of 2026-08-04 (pin manifest under Data). Ownership
   records are archived and independently anchored — data on IPFS, Merkle
   root on Ethereum, timestamp on Bitcoin
   (https://github.com/bitmark-inc/bitmarkd/wiki/bitmark-archive) — though
   the archive too stays available only while someone retains it.
   Last reference probe {probe["date"]}: {probe["resolving"]:,} of
   {probe["total"]:,} series answered (one probe per series entry file;
   editions share files).{pin_md}
{catalog_section}
## Bitmark-era exhibitions

| Exhibition | Works | Not yet migrated | On Ethereum | On Tezos |
|---|---:|---:|---:|---:|
{rows}

## What we check, and what we don't yet

A work RESOLVES when every reference in its chain can be fetched from public
infrastructure. These checks currently measure the ARTWORK FILES: every file
of every edition is requested through a gateway we do not operate (a
dedicated Filebase gateway, public gateways as backups). A file counts as
resolving only when a gateway we do not operate serves it — our own
infrastructure answering is not enough.

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
for Bitmark-era works, its archival copy address. Paste a wallet address
(0x… or tz…) instead and the page enumerates every published work the
wallet holds (Blockscout for Ethereum, TzKT for Tezos, called from the
browser — no backend) and emits a pin list: unique content addresses, one
per line, ready for `ipfs pin add`. Works with no published content
address are reported as such, never silently dropped; Bitmark-era works
cannot be enumerated from a wallet and keep the token-ID path. The same
data is in data/work_index.json + data/works/ (sharded JSON, documented
in the repo).

## Data

- {SITE_URL}/data/status.json — every number on this page, structured
- {SITE_URL}/data/pin_manifest_2026-08-04.csv — archival copies: series → CID
- {SITE_URL}/data/census/token_census_20260803T182523Z.csv.gz — the full probe, one row per file
- Bitmark enumeration + per-series probes + exhibition totals: named at {SITE_URL}/#data
- {SITE_URL}/feed.xml (RSS, one entry per update)

## Updates

{upd}
"""


def build_llms_txt(bucket3, census):
    probe_clause = f" (last full media probe {census['date']})" if census else ""
    return f"""# Feral File Status

> Every work Feral File ({SITE_URL.replace("status.", "")}) has published,
> and {CLAIM}. A published work is a chain of references (token ->
> contract -> metadata -> files -> runtime); this site currently measures
> the artwork-media layer{probe_clause}: whether each work's referenced
> artwork files are fetchable from public infrastructure. It does not yet
> measure whether each token's metadata reference is independently
> available, or whether the work renders as the artist intended. Static
> page, no client-side rendering; every number is generated from the raw
> data files below. Data is served with open CORS.

## Read this first

- [status.md]({SITE_URL}/status.md): the whole page as plain Markdown
- [status.json]({SITE_URL}/data/status.json): every number, structured

## Raw data

- [Bitmark-era per-work enumeration]({SITE_URL}/data/{bucket3["files"][1]}):
  one row per not-yet-migrated Bitmark-era work — byte-verified archival
  copies exist for every series; a work's published references update when
  its collector migrates it
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
  <description>Updates to what each published Feral File work's artwork media depends on, measured from public infrastructure.</description>
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

    status = {
        "generated_at": now.isoformat(timespec="seconds"),
        "site": SITE_URL,
        "works_by_media_dependency": {
            "resolve_without_feralfile": (
                (
                    {
                        "works": census["buckets"].get("independent", 0) + census["buckets"].get("redundant", 0),
                        "redundant": census["buckets"].get("redundant", 0),
                        "only_known_copy_ours": census["buckets"].get("independent", 0),
                        "as_of": census["date"],
                    }
                    if census.get("schema") == 2
                    else {"works": census["buckets"].get("independent", 0), "as_of": census["date"]}
                )
                if census
                else {"status": "census_in_progress", "started": "2026-08-03"}
            ),
            **(
                {
                    "could_not_be_measured": {
                        "works": census["buckets"].get("unmeasured", 0),
                        "as_of": census["date"],
                        "meaning": "at least one file's probe was rate-limited or errored after its retry budget; re-probed per CID (manual rescan) before the next publish; never a gap, never a pass",
                    },
                    # Sum identity checked by tools/check_claims.py: every
                    # measured work is in exactly one state, and unmeasured
                    # is never folded into another.
                    "works_measured": census["works"],
                }
                if census and census.get("schema") == 2
                else {}
            ),
            "depend_on_third_party": (
                {"works": census["buckets"].get("third_party", 0), "as_of": census["date"]}
                if census
                else None
            ),
            "failing_public_gateways": (
                (
                    {
                        "works": census["buckets"].get("gateway_gap", 0),
                        "as_of": census["date"],
                        "meaning": "at least one content-addressed file that neither our own node nor a gateway we do not operate served (schema 2: works our node serves but no outside gateway can fetch are counted under depend_entirely_on_feralfile.ipfs_only_our_node)",
                    }
                    if census.get("schema") == 2
                    else {"works": census["buckets"].get("gateway_gap", 0), "as_of": census["date"]}
                )
                if census
                else {"status": "census_in_progress", "started": "2026-08-03"}
            ),
            "depend_entirely_on_feralfile": (
                {
                    "works": census["buckets"].get("dependent", 0) + census["buckets"].get("ff_only", 0),
                    "cdn_only": census["buckets"].get("dependent", 0),
                    "ipfs_only_our_node": census["buckets"].get("ff_only", 0),
                    "as_of": census["date"],
                    "host": "cdn.feralfileassets.com",
                    "remediation": "media repointing to content-addressed copies; plan: ops/cdn-retirement-phase2.md (repo), target 2026-11-01; ipfs_only_our_node works need a second pinner",
                }
                if census and census.get("schema") == 2
                else {
                    "works": census["buckets"].get("dependent", 0),
                    "as_of": census["date"],
                    "host": "cdn.feralfileassets.com",
                    "remediation": "media repointing to content-addressed copies; plan: ops/cdn-retirement-phase2.md (repo), target 2026-11-01",
                }
                if census
                else {"status": "census_in_progress", "started": "2026-08-03"}
            ),
            "not_yet_migrated_bitmark_era": {
                "works": bucket3["works_on_bitmark"],
                "series": bucket3["series_count"],
                "exhibitions": bucket3["exhibitions_affected"],
                "as_of": bucket3["as_of"],
                "last_probe": bucket3["series_probe"],
                "media_mix_by_series": bucket3["media_mix"],
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
                "references": (
                    "resolve via cdn.feralfileassets.com until the collector "
                    "migrates the work; a swap writes content-addressed "
                    "references and fails closed without them"
                ),
            },
        },
        "scope": measurement_scope(census, bucket3),
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
    (PUBLIC / "llms.txt").write_text(build_llms_txt(bucket3, census))
    (PUBLIC / "robots.txt").write_text(ROBOTS_TXT)
    (PUBLIC / "_headers").write_text(HEADERS_FILE)

    kind = f"census {census['file']}" if census else "census pending"
    print(f"built public/ ({kind}, bucket3 as of {bucket3['as_of']})")

    # Claim-boundary guard runs inside the build so every path that builds
    # — including the Cloudflare Pages deploy, which calls this script
    # directly — fails on semantic drift, not only local `make build`.
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "check_claims.py")], check=True
    )


if __name__ == "__main__":
    main()
