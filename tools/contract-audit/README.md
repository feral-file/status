# contract-audit — population rebuild + on-chain tokenURI routing audit

*(formerly `tools/phase2-step0`)*

Step 0 of `ops/cdn-retirement-phase2.md`. Two scripts, run in order:

## 0a. population.py (offline, no credentials)

```
python3 tools/contract-audit/population.py \
    --census data/census/token_census_20260901T093949Z.csv \
    --goal2-result ops/bitmark-cdn-retirement/result.csv \
    --out-dir ops/cdn-retirement-phase2/step0
```

Rebuilds the phase-2 population from the fresh census: ETH tokens with media
on `cdn.feralfileassets.com` / `imagedelivery.net` (the doc's narrow fix
rule). Excludes Ten Whistlegraphs (API-overlay artifact), records
third-party-host rows separately, and cross-checks that no token phase 1
fixed reappears (exit 1 if any does).

2026-09-02 run (committed here): **11,517 tokens, 22,625 CDN media rows,
104 pin units** (61 directories + 43 bare shared-thumbnail files), 8
contracts — matches the plan doc's table exactly, goal-2 cross-check clean.

## 0b. check-base-uri.py (operator: needs RPC_URL)

```
RPC_URL=https://mainnet.infura.io/v3/<key> python3 tools/contract-audit/check-base-uri.py \
    --contracts ops/cdn-retirement-phase2/step0/population_by_contract.csv \
    --out ops/cdn-retirement-phase2/step0/base_uri_check.csv
```

Calls `tokenURI(sample)` on each population contract and verifies the plan's
routing assumptions as measured fact: V3 → FF gateway + trailing bare CID
(per-token chain txs needed), V4/V4_2 → feralfile.com API (**no chain txs
this phase** — the claim rests on this; a V4 contract whose live base URI is
not the API fails the run). Exit 1 on any expectation mismatch — do not
proceed to step 1 tooling for that contract until resolved.

Public RPCs are DNS-blocked on the office network — use Infura.
