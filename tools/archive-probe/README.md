# archive-probe

Does every CID the Feral File Archive manifest names resolve over public gateways?
(Condition 2 of the 2026-08-26 custody arrangement, feral-file#3435; prod-02 is the only
live node since ff-pin-1 was retired, 2026-10.)

```bash
python3 tools/archive-probe/probe.py                       # ipfs.io, dweb.link, ipfs.feralfile.com; ~230 CIDs
python3 tools/archive-probe/probe.py --deep                # also HEAD one child per directory CID
python3 tools/archive-probe/probe.py --gateways ipfs.io    # one gateway
```

Input: `data/archive-manifest.json` (every collection) + the newest `data/pin_manifest_*.csv`.
Output: `data/archive_probe_<utc>.csv`, one row per CID, one `<gateway>_ok` column each; failures listed on stderr.

A pass means *some* provider answered that gateway, not which one. Run it after each
prod-02 pin batch; commit the CSV so the claim is traceable.
