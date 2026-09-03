# ipfs-mirror — size, mirror, and pin CDN bytes onto the serving node

*(formerly `tools/phase2-step1`, built for CDN-retirement phase 2)*

Step 1 of `ops/cdn-retirement-phase2.md`: get the ~104 CDN pin units
(61 directories + 43 bare shared-thumbnail files, from step 0's
`cdn_dirs.csv`) onto prod-02 as pinned, verified IPFS content. Both scripts
are operator-run (origin-bucket credentials + the prod-02 tunnel).

## 1a. size-dirs.py — size everything BEFORE mirroring

```
BUCKET=<origin-bucket> python3 tools/ipfs-mirror/size-dirs.py \
    --dirs ops/cdn-retirement-phase2/step0/cdn_dirs.csv \
    --out ops/cdn-retirement-phase2/step1/dir_sizes.csv \
    --repo-used-gb <current> --storage-max-gb <current>
```

Lists each unit at the origin bucket (`aws s3 ls --recursive --summarize`,
`head-object` for bare files) — a CDN HEAD can't see inside software-preview
directories. Prints total GB and the prod-02 projection; warns above 90% of
StorageMax. **The crystalline `generated_images` answer comes out of this
run** — if the projection breaks headroom, settle capacity before 1b.
Resumable (done units skipped); `--dry-run` prints the aws commands.
Flags empty prefixes: bytes the CDN serves but the origin no longer holds
would silently vanish from the mirror otherwise.

## 1b. mirror-add-pin.sh — mirror → add → pin → verify, per unit

```
# in ff-deploy: make ipfs-port-forward ENV=prod HOST=prod-02
BUCKET=<origin-bucket> ./tools/ipfs-mirror/mirror-add-pin.sh \
    ops/cdn-retirement-phase2/step0/cdn_dirs.csv \
    ops/cdn-retirement-phase2/step1/dir_cids.csv
```

Per unit: `aws s3 sync` (dirs) / `cp` (bare files) → `ipfs add --cid-version 0`
through the tunnel (`-r` for dirs → dir CID; bare files get their own file
CID, phase-1 HLS style) → verify one sampled file **byte-compared** via
`ipfs.feralfile.com` and `ipfs.io` → append `unit,cid,…` to the record CSV
(step 2's reference-row input). The add pins by default — required under
prod-02's `Gateway.NoFetch=true` (ff-deploy#28).

- Resumable/idempotent: recorded units are skipped; rerun after interruption.
- Stops when repo exceeds `HEADROOM_STOP` (default 90%) of StorageMax.
- `ipfs.io` may lag the reprovide cycle → retried ×3 then recorded
  `public_pending` (re-verify after the next cycle; step 5's census is the
  final acceptance). A failure on `ipfs.feralfile.com` is a real error.
- Env: `API` (kubo multiaddr, default the tunnel), `WORK` (scratch),
  `KEEP=1` (retain mirrors), `HEADROOM_STOP`.

After 1b completes: rerun `tools/pin-referenced` is NOT yet needed (these
CIDs aren't referenced by the DB until step 2 writes the reference rows).
