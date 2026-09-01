# bitmark-pin

Mirror the 215 Bitmark-era series (397.6 GB, `data/pin_manifest_*.csv`) onto prod-02 so
`ipfs.feralfile.com` serves them. ff-pin-1 stays the custody node (decision 2026-08-26).

Prerequisites: prod-02 volume resized and `StorageMax` raised (ff-deploy#27), tunnel open
(`make ipfs-port-forward ENV=prod HOST=prod-02` in ff-deploy).

```bash
./tools/bitmark-pin/pin-on-prod02.sh     # peers with ff-pin-1, pin add each series CID; resumable; logs to pin.log
./tools/bitmark-pin/verify.sh            # every CID pinned recursively + 200 from the public gateway
```

`pin add` pulls the blocks from ff-pin-1 over the swarm (it holds every block but, as of 2026-08,
does not announce them — hence the explicit `swarm connect`). Expect hours for the full set.
Then run `tools/archive-probe` and `tools/bitmark-reference`.
