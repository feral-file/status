# Step-3 regen verification record (2026-09-03, verify-regen.py + light pass)

Independent of the regen tools' mapping logic.

## V3 (2,341 docs, six contracts) — full strength
- Doc integrity: **2,341/2,341** — reverse-substitution byte proof (substituting
  the new media values back yields the original on-chain doc byte-for-byte)
  + JSON key/value deep-equality outside media keys.
- Media 1:1 content: **1,782/1,782 deduped pairs** — old CDN URL (params
  intact, relative paths CDN-hosted) vs new ipfs target via ipfs.feralfile.com;
  full byte equality ≤4 MB, head-64KB + Content-Length above. Zero failures.
- Report: verify_v3.csv (empty = no failures).

## crystalline (9,048 docs) — per operator's spec (correspondence + samples)
- Doc integrity: **9,048/9,048** (same reverse-substitution byte proof).
- Offline correspondence, all tokens: animation **9,048/9,048** (query params
  incl. hourIdx byte-identical, same nft.html basename); image **9,048/9,048**
  (same filename, ?variant folded to the correct generated_images/<v>/ path).
- Content: nft.html CDN vs ipfs byte-identical (1,855 B, checked once —
  shared by all 9,048); random 30-image sample **30/30 byte-identical**
  (CDN ?variant URL vs folded ipfs path).

Conclusion: every regenerated doc differs from its on-chain original ONLY in
media values, and the media replacements are 1:1 (V3: fully content-proven;
crystalline: structurally proven for all + content-sampled).
