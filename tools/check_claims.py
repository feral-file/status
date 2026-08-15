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

if errors:
    print("claim-boundary check FAILED:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
print("claim-boundary check passed")
