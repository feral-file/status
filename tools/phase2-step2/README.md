# phase2 step 2 (Truth) — DB alignment with safety diff

See the docstring of `truth-db-align.py`. Needs the DB export
(`artwork_id,token_id,ipfs_cid` for contract 0xBb12686c…, 896 rows) from the
back-office host. Emits diff_report.csv, media_probe.csv, truth-align.sql
(WHERE-pinned, expect UPDATE 1 each); exit 1 on any diff-beyond-media or a
media CID unresolvable on ipfs.feralfile.com.
