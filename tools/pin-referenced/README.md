# pin-referenced

Make the set of CIDs the Feral File DB references explicit and pinned on the serving node.

```bash
# export from the DB (see ops/3435-hls-fix/db_referenced_cids.csv for the query) → one CID per line
python3 tools/pin-referenced/pin_referenced.py ops/3435-hls-fix/db_referenced_cid_list.txt            # dry run: present / missing
python3 tools/pin-referenced/pin_referenced.py ops/3435-hls-fix/db_referenced_cid_list.txt --pin      # pin what is present
```

Tunnel required (`make ipfs-port-forward ENV=prod HOST=prod-02`). Writes `<list>.pinstatus.csv` and
`<list>.missing.txt`. Missing CIDs are the real gaps (the 2026-08-25 "44 thumbnails" class): fetch them
from ff-pin-1, a public gateway or the origin, then rerun.

Why: on 2026-08-27 prod-02 served ~73k referenced CIDs with ~950 recursive pins; the rest were
gateway-era cache surviving only because the container runs kubo without `--enable-gc`.
