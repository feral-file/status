#!/usr/bin/env python3
"""Assemble archive-manifest.json — the document the FeralFileArchiveRegistry
contract points at.

Sources (data/):
  pin_manifest_<date>.csv        the 215 Bitmark-era series (byte-verified)
  bitmark_series_media_<date>.csv  series titles/artists for readability
  archive_pins_<date>.json       a2p, the Bitmark chain archive, HLS masters

Output: archive-manifest.json (stdout path printed). Add it to IPFS, pin it,
then call setManifest(<cid>) on the registry.
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"


def latest(pattern):
    matches = sorted(DATA.glob(pattern))
    if not matches:
        raise SystemExit(f"missing input: {pattern}")
    return matches[-1]


def main():
    pins = list(csv.DictReader(open(latest("pin_manifest_*.csv"))))
    series_meta = {
        r["series_id"]: r
        for r in csv.DictReader(open(latest("bitmark_series_media_*.csv")))
    }
    extra = json.loads(latest("archive_pins_*.json").read_text())

    unverified = [p["series_id"] for p in pins if p["verified"] != "true"]
    if unverified:
        raise SystemExit(f"refusing to build: unverified series {unverified[:3]}")

    series_items = []
    for p in pins:
        meta = series_meta.get(p["series_id"], {})
        series_items.append(
            {
                "series_id": p["series_id"],
                "title": meta.get("series_title") or None,
                "artist": meta.get("artist") or None,
                "exhibition": meta.get("exhibition_slug") or None,
                "cid": p["cid"],
                "bytes": int(p["bytes"]),
                "files": int(p["files"]),
                "verified_at": p["synced_at"],
            }
        )

    manifest = {
        "name": "Feral File Archive",
        "description": (
            "Content-addressed, byte-verified copies of works Feral File "
            "preserves. Every CID below can be pinned by anyone; each copy "
            "held anywhere makes the works more permanent. Published by "
            "Feral File; the current CID of this document is recorded in the "
            "FeralFileArchiveRegistry contract on Ethereum."
        ),
        "site": "https://status.feralfile.com",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "collections": [
            {
                "id": "bitmark-era-series",
                "description": (
                    "Complete media of the 215 series from Feral File's "
                    "Bitmark-era exhibitions (4,959 never-migrated works plus "
                    "the migrated editions that share these files), synced "
                    "from the origin store and verified byte-for-byte. One "
                    "CID per series, wrapping artworks/ and previews/."
                ),
                "items": series_items,
            }
        ]
        + extra["collections"],
    }

    out = DATA / "archive-manifest.json"
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    total = sum(i["bytes"] for i in series_items)
    print(f"{out}")
    print(
        f"bitmark-era: {len(series_items)} series, {total/1e9:.1f} GB; "
        f"extra collections: {[c['id'] for c in extra['collections']]}"
    )


if __name__ == "__main__":
    main()
