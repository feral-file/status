-- #7 Primordium deep analysis (read-only). Contract 0x513AC47320798fB6D74543242a9c0F686682998D.
-- Q1: preview upload history per series — every ipfs_reference row under the series' previews/ prefix,
--     with the timestamp folder (unix seconds) decoded, and whether it is the CURRENT preview_uri.
\copy (
  WITH s AS (
    SELECT se.id AS series_id, se.title, se.medium, se.updated_at AS series_updated_at,
           (SELECT a.preview_uri FROM artworks a WHERE a.series_id = se.id LIMIT 1) AS current_preview_uri,
           (SELECT count(*) FROM artworks a WHERE a.series_id = se.id) AS artworks
    FROM series se JOIN exhibition e ON e.id = se.exhibition_id
    WHERE e.title = 'Primordium'
  )
  SELECT s.title, s.series_id, s.medium, s.artworks, s.series_updated_at,
         r.uri AS reference_uri, r.ipfs_uri,
         to_timestamp((regexp_match(r.uri, 'previews/[^/]+/(\d{10})/'))[1]::bigint) AS upload_time,
         r.created_at AS reference_created_at, r.updated_at AS reference_updated_at,
         (r.uri = s.current_preview_uri) AS is_current_preview
  FROM s JOIN ipfs_reference r ON r.uri LIKE 'previews/' || s.series_id::text || '/%'
  ORDER BY s.title, upload_time
) TO '/Users/yehboyang/status/ops/3435-hls-fix/primordium_preview_history.csv' CSV HEADER

-- Q2: per token — swap record, its metadata cid, the artwork's current preview/thumbnail and their references.
--     Join with tools/v2-metadata-regen/audit.csv (contract, token_id) to see what the chain says.
\copy (
  SELECT se.title, a.index AS edition, a.id AS artwork_id, s.token AS token_id, s.ipfs_cid AS swap_metadata_cid,
         s.status, s.is_migration, s.created_at AS swap_created_at, s.updated_at AS swap_updated_at, s.tx_id,
         a.preview_uri, p.ipfs_uri AS preview_ipfs_uri, a.thumbnail_uri, t.ipfs_uri AS thumbnail_ipfs_uri,
         a.updated_at AS artwork_updated_at
  FROM swaps s
  JOIN artworks a ON a.id = s.artwork_id
  JOIN series se ON se.id = a.series_id
  JOIN exhibition e ON e.id = a.exhibition_id
  LEFT JOIN ipfs_reference p ON p.uri = a.preview_uri
  LEFT JOIN ipfs_reference t ON t.uri = a.thumbnail_uri
  WHERE e.title = 'Primordium' AND s.blockchain_type = 'ethereum' AND s.status = 'complete'
  ORDER BY se.title, a.index
) TO '/Users/yehboyang/status/ops/3435-hls-fix/primordium_tokens.csv' CSV HEADER

-- Q3: the 28 tokens whose on-chain metadata dir is unservable — is there any other record of the cid the chain holds?
--     (paste the 28 onchain_cid values from audit.csv rows with error 'fetch failed' on contract 0x513ac4…)
SELECT 'swaps' AS src, id::text, ipfs_cid, status, updated_at FROM swaps WHERE ipfs_cid IN ('QmP3Cr9Ww7PZuP5xYPoXAsUqRMhy278qFYfKhqJ7Jr7o7P','QmZYYZquK5sqAJcfiVdCyV8W8vVd6FVsEer3qMCDpvccVy','Qmf9p5JnrhGEx9Qt2tuJGJ8992Y265rVKV8VbUkJ8cV7di','QmTrcaA28dwHBjR7wjfUq6oicjEovCsAK6ba2W9h45nCR7','QmdZ5sCetTQ2tLckcB2MbDTyAF4LFLwqwg7FHuE7zMjjXN','QmXvLrUWxQ7eERPvPqTRm5r2GX97tfYGxPjMWeGo2k94aJ','QmfSPqTXr7qPsek9c93Q9anJ8meKy9LZyodsJtdWVFAVdZ','QmbrQt3BFeErEhrv5n23k7ZrL1NXW7VMMApM9kWe5oveVd','QmfWqmAUfvNib5D1vviexohdQdG7QLVNXEWdyu6EjRwzZ8','QmURL2BCYdyjXhGwbAAPHMJiHSjsPk5iM5euNmaReAJWfe','QmPCQroWjLH7yEWa9AhTyLknwWj6HEHEx99dA4ZTkKzxQr','QmPVjEiU8m5sYDU8jkb9oKCdWGsyj687ouBZQtZvuJJpnx','QmTkEE3SwFmc5TxzfmDcKngHg2d3baYtnhPJpYZqtENey1','QmPTcYZj8FSQjZSQo1c5gQGZgZ94n7PuDmZqKNT7LLfAwt','QmbGjMAsLDY2rXzTBpEb3X6K62EuUnCXjPAU4MhCikcMgu','QmUgVicvXcoCw8JsKPcBK1dGjn6StLzW5fWHjHzKyhJVPE','QmfJ5A3RYpNuxnc5FkJ2jHAaWqmtahb1dPoju9aJmfn5PZ','QmYF2DYj1hcEzCzM1P6euoQQEG4VqEqi6Wr7JLmkids1rG','QmZKSQCGptf9KEdWHiE8vRjyKxc4KTb8Fs2aEqNXiWpjLn','QmUKoE3j7pbFpnoHMCAX9Mf5WtU1eTfWjwBC9oGEnDEJSz','QmTdGVdGm58UTzuj5MoTEofF4SB3nCXRETbgahyowAyHMq','QmXF3wzxarA6NnW2XyvTqtMEuTD8CVpVPmWTMZANPdTSEN','QmYFwsBnUb1sVGuCeCgr4cxirbudc6T7YZTkRguKG58K3t','Qmdkq29thGhqg7cLH2PQtvzrWZCX8rLR8NPM44Gjwr5uN1','QmbPvj97Z91Z19Fct9aTZWR3xSPAfkDgf4RAiQNA66jxYj','QmZkJ3fxQdp2fvtKRV8LuffmkcbA8gPCUvo4yEH7gugUvC','QmNsrBdo4hybLbSf3ZXVpUcSvYqEyN7QuuVwjKhJWX7Q8t','QmZxWAqHMrMfSekA3mPZwsLmosDwCZyEedBD3X8zTLxWLy')
UNION ALL
SELECT 'artworks', id, metadata->>'ipfs_cid', NULL, updated_at FROM artworks WHERE metadata->>'ipfs_cid' IN ('QmP3Cr9Ww7PZuP5xYPoXAsUqRMhy278qFYfKhqJ7Jr7o7P','QmZYYZquK5sqAJcfiVdCyV8W8vVd6FVsEer3qMCDpvccVy','Qmf9p5JnrhGEx9Qt2tuJGJ8992Y265rVKV8VbUkJ8cV7di','QmTrcaA28dwHBjR7wjfUq6oicjEovCsAK6ba2W9h45nCR7','QmdZ5sCetTQ2tLckcB2MbDTyAF4LFLwqwg7FHuE7zMjjXN','QmXvLrUWxQ7eERPvPqTRm5r2GX97tfYGxPjMWeGo2k94aJ','QmfSPqTXr7qPsek9c93Q9anJ8meKy9LZyodsJtdWVFAVdZ','QmbrQt3BFeErEhrv5n23k7ZrL1NXW7VMMApM9kWe5oveVd','QmfWqmAUfvNib5D1vviexohdQdG7QLVNXEWdyu6EjRwzZ8','QmURL2BCYdyjXhGwbAAPHMJiHSjsPk5iM5euNmaReAJWfe','QmPCQroWjLH7yEWa9AhTyLknwWj6HEHEx99dA4ZTkKzxQr','QmPVjEiU8m5sYDU8jkb9oKCdWGsyj687ouBZQtZvuJJpnx','QmTkEE3SwFmc5TxzfmDcKngHg2d3baYtnhPJpYZqtENey1','QmPTcYZj8FSQjZSQo1c5gQGZgZ94n7PuDmZqKNT7LLfAwt','QmbGjMAsLDY2rXzTBpEb3X6K62EuUnCXjPAU4MhCikcMgu','QmUgVicvXcoCw8JsKPcBK1dGjn6StLzW5fWHjHzKyhJVPE','QmfJ5A3RYpNuxnc5FkJ2jHAaWqmtahb1dPoju9aJmfn5PZ','QmYF2DYj1hcEzCzM1P6euoQQEG4VqEqi6Wr7JLmkids1rG','QmZKSQCGptf9KEdWHiE8vRjyKxc4KTb8Fs2aEqNXiWpjLn','QmUKoE3j7pbFpnoHMCAX9Mf5WtU1eTfWjwBC9oGEnDEJSz','QmTdGVdGm58UTzuj5MoTEofF4SB3nCXRETbgahyowAyHMq','QmXF3wzxarA6NnW2XyvTqtMEuTD8CVpVPmWTMZANPdTSEN','QmYFwsBnUb1sVGuCeCgr4cxirbudc6T7YZTkRguKG58K3t','Qmdkq29thGhqg7cLH2PQtvzrWZCX8rLR8NPM44Gjwr5uN1','QmbPvj97Z91Z19Fct9aTZWR3xSPAfkDgf4RAiQNA66jxYj','QmZkJ3fxQdp2fvtKRV8LuffmkcbA8gPCUvo4yEH7gugUvC','QmNsrBdo4hybLbSf3ZXVpUcSvYqEyN7QuuVwjKhJWX7Q8t','QmZxWAqHMrMfSekA3mPZwsLmosDwCZyEedBD3X8zTLxWLy');
-- expect 0 rows: the chain's cids are known nowhere in the DB
