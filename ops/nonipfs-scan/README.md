# nonipfs-scan runs

Run records for `tools/nonipfs-scan/scan.py` (live health scan of every
non-IPFS media URL the census references). State jsonl is gitignored; the
results CSV is the record.

## 2026-09-02 — first run (results_2026-09-02.csv)

Population: census 2026-09-01, 20,016 distinct non-IPFS media URLs
(cdn.feralfileassets.com 20,006, aesthetic.computer 10). Probed live from
a residential connection, 12 workers, GET Range 0-1023, retries ×3.

**Result: 5 broken, everything else healthy.** All five are one series:

- Exhibition: I KNOW – On the aesthetic of truth (`99aa32cb`), contract
  `0xE46A41b840176b62983FC71162dc9faEAC4D9bcB` (V3)
- Series: The Art of Survival: Aphorisms by an Old Girl, Claudia Hart
  (`6ed56114-2768-4625-84a9-7eda5baad6b8`), 5 editions
- Broken: `image` → `previews/6ed56114…/1673657166/_unique-thumbnails/{0..4}-large.jpg`,
  HTTP 403 (object absent). `animation_url` → `…/preview.mp4` in the same
  directory is healthy.

Root cause (from feral-file-server source + the series API): the series is
`ArtworkModel = multi_unique`, so metadata generation emits per-edition
`_unique-thumbnails/<idx>-large.jpg` image URIs
(`internal/domain/artwork/artwork.go`), but the series has
`manualGenerateUniqueThumbnails = false` and the files were never uploaded —
403 in every census (8/3, 8/25, 9/1), i.e. broken since mint
(ts 1673657166 = 2023-01-14). The series-level thumbnail
`thumbnails/6ed56114…/1673658137` exists (200, image/jpeg, 166 KB) and is
the natural replacement bytes.

The census had recorded these five 403s each time; nothing surfaced them —
that gap is what this tool closes (found by hand 2026-09-02,
feral-file/feral-file#3435).

**Fixed 2026-09-02 (option A, Brandon):** thumbnail files restored at the
origin-bucket keys. Verified live: all five URLs return 200 `image/jpeg`
(48–176 KB, distinct files per edition). With that, the full first-run
population reads 20,016/20,016 healthy.
