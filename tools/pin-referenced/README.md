# pin-referenced

Make the set of CIDs the Feral File DB references explicit and pinned on the serving node.

```bash
# export from the DB (query below) → one CID per line
python3 tools/pin-referenced/pin_referenced.py referenced_cids.txt            # dry run: present / missing
python3 tools/pin-referenced/pin_referenced.py referenced_cids.txt --pin      # pin what is present
```

Tunnel required (`make ipfs-port-forward ENV=prod HOST=prod-02`). Writes `<list>.pinstatus.csv` and
`<list>.missing.txt`. Missing CIDs are the real gaps (the 2026-08-25 "44 thumbnails" class): fetch them
from ff-pin-1, a public gateway or the origin, then rerun.

Why: on 2026-08-27 prod-02 served ~73k referenced CIDs with ~950 recursive pins; the rest were
gateway-era cache surviving only because the container runs kubo without `--enable-gc`.

DB export (one CID per line after extracting the CID from each ref):

```sql
\copy (
  SELECT ipfs_uri AS ref FROM ipfs_reference
  UNION SELECT ipfs_cid FROM swaps WHERE ipfs_cid <> ''
  UNION SELECT metadata->>'ipfs_cid' FROM artworks WHERE metadata->>'ipfs_cid' IS NOT NULL
) TO 'referenced_refs.csv' CSV HEADER
```

Add the CIDs the chain references but the DB does not (`census` CSV `cid` column minus the DB set) — 198 of them on 2026-08-28.
Results of the first run: `ops/3435-hls-fix/pin_referenced_2026-08-28.csv` (73,385) and `pin_chain_only_2026-08-28.csv` (198).
