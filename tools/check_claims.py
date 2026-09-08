#!/usr/bin/env python3
"""Claim-boundary regression check, run by `make build` after every build.

The failure this guards against is semantic drift: a summary surface
quietly claiming more than the probes measure. It checks only the
top-level self-descriptions (HTML meta + lede, status.md opening,
llms.txt blockquote, RSS channel description, status.json scope). The
method section legitimately discusses the phrase "it still works" and is
deliberately not checked.
"""

import json
import re
import sys
from pathlib import Path

PUBLIC = Path(__file__).parent.parent / "public"
errors = []


def check(surface, ok, msg):
    if not ok:
        errors.append(f"{surface}: {msg}")


page = (PUBLIC / "index.html").read_text()
meta = re.search(r'<meta name="description" content="([^"]*)"', page).group(1)
check("meta description", "artwork media" in meta, "must name the artwork-media layer")
check("meta description", "whether it still works" not in meta,
      "overclaims: 'whether it still works'")

lede = re.search(r'<p class="lede">(.*?)</p>', page, re.S).group(1)
check("lede", "artwork files" in lede, "must name the artwork files")
check("lede", "not yet measured" in lede,
      "must state the metadata-link + rendering boundary")
check("lede", re.search(r"last probed \d{4}-\d{2}-\d{2}", lede),
      "must show the probe date, distinct from the Generated footer")

def flat(text):
    """Collapse line wraps and blockquote prefixes so phrase checks are
    robust to reflowing."""
    return " ".join(text.replace("\n>", " ").split())


md_head = flat((PUBLIC / "status.md").read_text()[:600])
check("status.md", "artwork media" in md_head, "opening must name the artwork-media layer")
check("status.md", "whether it still works" not in md_head,
      "overclaims: 'whether it still works'")
check("status.md", "not yet measured" in md_head, "opening must state the boundary")

llms = flat((PUBLIC / "llms.txt").read_text())
check("llms.txt", "artwork-media layer" in llms, "must name the measured layer")
check("llms.txt", "whether each link answers" not in llms,
      "overclaims: 'reports whether each link answers'")
check("llms.txt", "whether it still works" not in llms,
      "overclaims: 'whether it still works'")
check("llms.txt", "does not yet measure" in llms, "must state both open limits")

feed = (PUBLIC / "feed.xml").read_text()
channel_desc = re.search(r"<description>(.*?)</description>", feed, re.S).group(1)
check("feed.xml", "artwork media" in channel_desc,
      "channel description must name the media layer")
check("feed.xml", "still works" not in channel_desc, "overclaims: 'still works'")

scope = json.loads((PUBLIC / "data" / "status.json").read_text())["scope"]
check("status.json", scope.get("layer") == "artwork_media",
      "scope.layer must be artwork_media")
open_limits = " ".join(scope.get("not_yet_measured", []))
check("status.json", "metadata link" in open_limits and "renders" in open_limits,
      "scope must keep both open limits (metadata link, rendering)")
check("status.json",
      bool(scope.get("media_probe_as_of") or scope.get("bitmark_reference_probe_as_of")),
      "scope must carry a probe date, separate from generated_at")

status = json.loads((PUBLIC / "data" / "status.json").read_text())
w = status["works_by_media_dependency"]
if "could_not_be_measured" in w:
    # Census schema 2: every measured work sits in exactly one state, and
    # `unmeasured` is a state of its own -- never folded into a pass or a
    # gap. A drift here means a rate limit became a claim.
    parts = {
        "resolve_without_feralfile": w["resolve_without_feralfile"]["works"],
        "failing_public_gateways": w["failing_public_gateways"]["works"],
        "depend_entirely_on_feralfile": w["depend_entirely_on_feralfile"]["works"],
        "depend_on_third_party": w["depend_on_third_party"]["works"],
        "could_not_be_measured": w["could_not_be_measured"]["works"],
    }
    total = w.get("works_measured")
    check("status.json", total is not None, "schema 2 must publish works_measured")
    check("status.json", sum(parts.values()) == total,
          f"media states must partition works_measured: {parts} != {total}")
    rw = w["resolve_without_feralfile"]
    check("status.json", rw.get("redundant", 0) + rw.get("only_known_copy_ours", 0) == rw["works"],
          "resolve_without_feralfile must equal redundant + only_known_copy_ours")
    # Independent recount from the published census itself (the sum
    # identity alone cannot see an unmeasured work quietly moved into
    # another bucket): a work is unmeasured when at least one of its
    # content-addressed files is, and none is unreachable / ff_only
    # (worse states win the roll-up).
    import csv, gzip
    gz = sorted((PUBLIC / "data" / "census").glob("token_census_*.csv.gz"))
    check("status.json", bool(gz), "schema 2 must publish the census CSV")
    if gz:
        per_work = {}
        with gzip.open(gz[-1], "rt", encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if r["resource"] == "metadata" or not r["cid"]:
                    continue
                per_work.setdefault((r["chain"], r["contract"], r["token_id"]), set()).add(r.get("verdict") or "unmeasured")
        recount = sum(
            1 for vs in per_work.values()
            if "unmeasured" in vs and not vs & {"unreachable", "ff_only"}
        )
        check("status.json", recount == w["could_not_be_measured"]["works"],
              f"could_not_be_measured.works ({w['could_not_be_measured']['works']}) must equal the CSV recount ({recount})")
    page_text = flat(page)
    check("index.html", "could not be measured" in page_text,
          "schema 2 must show the unmeasured state on the page")

if errors:
    print("claim-boundary check FAILED:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
print("claim-boundary check passed")
