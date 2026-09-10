# Repo cleanup — retention policy and cleanup log

*The rule applied before every merge into `main`. Written 2026-09-04 (as the plan for PR #12),
rewritten in English and extended 2026-09-10. Owner: Brandon.*

## Policy

**`ops/`** keeps only what an operation needs to be understood, audited, or reversed:

- keep: the narrative (`README.md` / `STATUS.md` / incident docs), decision records, small
  summary tables, registries later steps depend on (pin-unit lists, per-token old→new
  mappings, "carry these CIDs into the next pin run" lists), receipts of a state that no
  longer exists and cannot be re-measured (a *before* snapshot), external inputs we did not
  produce (OpenSea's attachments, a partner's reply), and the tools bound to that operation
  (`ops/<op>/tools/`).
- delete once the conclusion is written down: anything recomputable from an authority
  (chain, IPFS pins, the indexer, a public API, a fresh DB export) — per-token dumps, DB
  exports, probe/scan outputs, resumable scanner state, applied SQL (the generator and its
  inputs stay), build trees, mirrors, logs, and anything explicitly superseded.

**`tools/`** keeps only tools that are generic over a class (a contract family, a DB table,
a node) and are named by function. A script bound to one exhibition, series, or one-off
migration lives under `ops/<op>/tools/`; a tool prepared for a case that never ran is
deleted, not archived.

**Everything is English** — documents, comments, commit messages. Non-English strings inside
data files (artwork and series names) are data, not prose.

Order of work, never changed: **commit the keepers first → delete → move/rename → fix every
path reference (`grep`, expect zero hits) → refresh the docs → verify.** Untracked deletions
cannot be recovered from git, so each one is checked against its authoritative copy first.

## Log

### 2026-09-04 — PR #12 (`e482085`), ~29.6 GB removed

- Untracked mirror (`phase2-mirror`, 29 G; 104/104 units pinned on prod-02 and
  byte-verified, `step1/dir_cids.csv` is the registry), local media scratch (`hls`), the
  step-3 doc trees (117 M, all pinned, regen tools kept), the V2 regen intermediates
  (`src/ runs/ updates/`, 138 M; the 23-contract rollout list was copied into `STATUS.md`).
- `ops/cdn-retirement-phase2`: pin-referenced intermediates, DB exports (`step2/*_export.csv`),
  applied align SQL + skip logs, reference-review CSVs, the large step-0 audits
  (`population_tokens.csv`, `v3_audit.csv`, `v4_audit_*.csv` + state), the delist scanner
  state; `ops/nonipfs-scan` (conclusion = status PR #10); `bitmark-cdn-retirement` audit +
  export; `3435-hls-fix/pin_referenced_2026-08-28.csv` (superseded by the 9/4 run).
- `tools/` reorganised by function with `git mv`: `phase2-step0 → contract-audit`,
  `phase2-step1 → ipfs-mirror`, `v2-metadata-regen + phase2-step3 → metadata-regen`,
  SQL generators → `db-align-sql`, OpenSea scanners → `opensea`, `bitmark-pin → ipfs-pin`.
- `HANDOFF-2026-09-04.md` rewritten as `STATUS.md`; `.gitignore` gained `.DS_Store`,
  `ops/**/*.state.jsonl`, `tools/**/progress.json`.

Explicitly kept, with the reason: `step1/dir_cids.csv` + `dir_sizes.csv` (pin-unit registry,
the only basis for the unpin phase); `step3/updates_0x*.csv` (2,341 old→new doc mappings);
`step3/staging_roots.csv`, `VERIFICATION.md`, `verify_v3.csv`, `regen_failures.csv`
(receipts); `step2/export-*.sql` (tools, not data); `step2/reference-fix-dirlisting.sql`
(182-row repair decision record); `opensea_delist_report.csv` (final scan of an open
incident); `ops/opensea-metadata-path/*` (incident open); `RUNBOOK-crystalline-base-uri.md`
(tx was pending); `tools/update-token-uri/v4-base-uri.config.json` (live, gitignored,
holds a vault account id — never committed, kept only until the tx landed).

### 2026-09-10 — branch `tools/phase2-step0` before merge

- `ops/special-project-contracts`: per-token dumps removed — `special_project_tokens.csv`
  (992 rows) and `round2_tokens.csv` (206) from `tools/audit-contracts.py`,
  `round2_chain_tokens.csv` (Blockscout), `round2_ffapi_tokens.csv` (FF API), the two
  media-CID HEAD probes, `prod02_unpinned_cids.txt` (a filter of the kept *before*
  snapshot), `indexer_releases_feralfile.csv` (unused walk derivative),
  `zero_token_contracts_chain.csv` (superseded). Kept: the population and summary tables,
  `prod02_pin_status_before.csv` (not reproducible) and `prod02_pin_status.csv` (the CID
  list for future pin runs). Regeneration commands are in that README.
- `ops/cdn-retirement-phase2/filum`: the applied `filum-align.sql` (896 UPDATEs, 2026-09-08)
  removed; `tools/gen-filum-sql.py` + `cids.csv` + `doc_updates.csv` + a fresh export
  regenerate it (and its reverse, if the owner tx is ever abandoned).
- `tools/`: `db-align-sql/truth-db-align.py` deleted — a Truth-specific align tool prepared
  on 2026-09-02 for a case that turned out not to exist (the DB was already in path form);
  the filum fix used `gen-filum-sql.py`. The filum tx template moved out of `tools/`:
  `tools/update-token-uri/v4-base-uri.config.filum.example.json →
  ops/cdn-retirement-phase2/filum/v4-base-uri.config.example.json`.
- This file: `repo-cleanup-2026-09-04.md` (Chinese, an executed plan) → `repo-cleanup.md`
  (English, policy + log). `.gitignore` comment for the filum build tree pointed at the old
  tool path; fixed.
- Local only: `.DS_Store`, `__pycache__/`, and the live `v4-base-uri.config.json` (the
  crystalline tx landed 2026-09-08, filum's the same day — its vault account id has no
  reason to stay on disk). Left alone: `public/` (CI builds the page), `node_modules/`.
