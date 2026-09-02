# nonipfs-scan — live health scan of every non-IPFS media URL

Probes every distinct non-IPFS media URL the census references (hosting
`cdn`/`other`, resource ≠ metadata) the way a browser would, and turns the
failures into a fix list. Exists because the census records per-row
`http_status` for CDN media but nothing ever surfaced the failures: the
2026-09-01 census carried five `_unique-thumbnails/N-large.jpg` 403s
(I KNOW, `99aa32cb`) that were only noticed when a human hit one
(feral-file/feral-file#3435, 2026-09-02).

## Run

```
python3 tools/nonipfs-scan/scan.py \
    --census data/census/token_census_20260901T093949Z.csv \
    --state  ops/nonipfs-scan/state_2026-09-02.jsonl \
    --out    ops/nonipfs-scan/results_2026-09-02.csv
```

- Probe: `GET` with `Range: bytes=0-1023`, browser User-Agent, redirects
  followed; ok = HTTP 200/206 with a non-empty body. Retries ×3 with
  backoff on 429/5xx/network errors.
- Resumable: results append to `--state` as they land; rerun to continue.
  `--reprobe-failed` re-probes stored failures instead of trusting them.
  Delete the state file between censuses.
- `--include-metadata` extends the population to the metadata endpoint
  URLs (feralfile.com API, tzkt) — normally unnecessary: every census run
  fetches those itself (`Metadata errors` in the summary).
- Exit 1 when anything is broken (cron-friendly); stdout ends with the
  failures grouped by CDN directory with affected token counts.

## Output

`--out` CSV, one row per distinct URL: `url, host, ok, status,
content_type, attempts, error, n_token_rows, resources, exhibitions,
example_contract, example_token_id`. Run data belongs in `ops/`
(logic only in `tools/`, per repo policy).

## Relation to the census

Same population, independent verdict: this scans live, so it catches
breakage that happened after census time and clears entries that were
census-time transients. It does NOT extend the population — a URL that no
token metadata references is invisible here, same as in the census.
