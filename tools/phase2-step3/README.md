# phase2 step 3 (V4/V4_2) — rebuild the tokenId-named metadata dir

See the docstring of `v4-dir-regen.py`. Byte-preserving media-key rewrite of
the on-chain docs (crystalline: 9,048), driven by step 1b dir_cids.csv.
Smoke-tested 2026-09-02 on 3 tokens: only image/animation_url change, query
params preserved (incl. image ?variant=small), all other bytes identical.
After regen: ipfs add -r --hidden --cid-version 0 via the tunnel, ONE
setTokenBaseURI("ipfs://<newDir>/") owner tx, then DB align to the new doc
CIDs (add -r without -Q lists per-file CIDs).
