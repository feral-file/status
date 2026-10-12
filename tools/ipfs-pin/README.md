# ipfs-pin — byte-verified series/file pinning on prod-02

*(formerly `tools/bitmark-pin` + root `pin_works.sh`/`pin_files.sh`)*

prod-02 (`ipfs.feralfile.com`) is the archival node: it holds the Feral File Archive
and serves it. ff-pin-1, the custody node it was mirrored from (feral-file#3435), is
retired (2026-10, ff-deploy#51); the other copy is prod-02's S3 Deep Archive backup.

The scripts run on your machine with a local `ipfs` CLI (kubo 0.43) pointed at prod-02
through the tunnel: the CLI talks to whatever API `$IPFS_PATH/api` names.

```bash
make ipfs-port-forward ENV=prod HOST=prod-02          # in ff-deploy; confirm /api/v0/id is prod-02
mkdir -p ~/.ipfs-prod02 && echo /ip4/127.0.0.1/tcp/5001 > ~/.ipfs-prod02/api
export IPFS_PATH=~/.ipfs-prod02

./tools/ipfs-pin/pin-works.sh <series_csv> <manifest_out.csv>   # series dirs from the origin bucket
./tools/ipfs-pin/pin-files.sh <manifest_out.csv> <file> ...     # loose files
./tools/ipfs-pin/verify.sh [pin_manifest.csv]                   # pinned recursively + 200 from the gateway
```

`pin-works.sh` also needs AWS credentials that can read the origin bucket
(`s3://feralfile-assets-livenet`, `aws s3 sync`), and local disk for two copies of a series:
`add` uploads it over the tunnel and the round-trip check `get`s it back, so each series
crosses the link twice. Scripts are portable bash (macOS or Linux) plus `python3`.
New content is in the Deep Archive after the next weekly `ipfs_archive` export (Saturday).
Then run `tools/archive-probe` and `tools/db-align-sql`.
