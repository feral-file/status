# ipfs-pin — byte-verified series/file pinning on prod-02

*(formerly `tools/bitmark-pin` + root `pin_works.sh`/`pin_files.sh`)*

Mirror the 215 Bitmark-era series (397.6 GB, `data/pin_manifest_*.csv`) onto prod-02 so
`ipfs.feralfile.com` serves them. ff-pin-1 stays the custody node (decision 2026-08-26).

Prerequisites: prod-02 volume resized and `StorageMax` raised (ff-deploy#27), tunnel open
(`make ipfs-port-forward ENV=prod HOST=prod-02` in ff-deploy).

```bash
./tools/ipfs-pin/pin-on-prod02.sh     # peers with ff-pin-1, pin add each series CID; resumable; logs to pin.log
./tools/ipfs-pin/verify.sh            # every CID pinned recursively + 200 from the public gateway
```

`pin add` pulls the blocks from ff-pin-1 over the swarm (it holds every block but, as of 2026-08,
does not announce them — hence the explicit `swarm connect`). Expect hours for the full set.
Then run `tools/archive-probe` and `tools/db-align-sql`.
