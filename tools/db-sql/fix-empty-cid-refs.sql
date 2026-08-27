-- Fix ipfs_reference rows whose ipfs_uri lost its CID: 'ipfs://?edition_number=…'
-- (166 rows on 2026-08-28, all Tezos software editions). feral-file#3435.
--
-- Cause: internal/tasks/ipfs.go ensureIPFSReferenceForURI builds the query row
-- as <path row's ipfs_uri> + '?' + query; when the path row's ipfs_uri was empty
-- at that moment the result is 'ipfs://?…'. The path row is the source of truth,
-- so rebuild the query rows from it. Nothing is pushed to IPFS here.

BEGIN;

-- 0 · what is broken, and whether each has a usable path row
SELECT r.uri, r.ipfs_uri AS broken, p.ipfs_uri AS path_row
FROM ipfs_reference r
LEFT JOIN ipfs_reference p ON p.uri = split_part(r.uri, '?', 1)
WHERE r.ipfs_uri LIKE 'ipfs://?%'
ORDER BY r.uri;

SELECT count(*) AS broken,
       count(*) FILTER (WHERE p.ipfs_uri LIKE 'ipfs://%' AND p.ipfs_uri NOT LIKE 'ipfs://?%') AS fixable_from_path_row,
       count(*) FILTER (WHERE p.uri IS NULL) AS no_path_row,
       count(*) FILTER (WHERE p.uri IS NOT NULL AND (p.ipfs_uri IS NULL OR p.ipfs_uri = '' OR p.ipfs_uri LIKE 'ipfs://?%')) AS path_row_also_empty
FROM ipfs_reference r
LEFT JOIN ipfs_reference p ON p.uri = split_part(r.uri, '?', 1)
WHERE r.ipfs_uri LIKE 'ipfs://?%';
-- expect broken = fixable_from_path_row = 166. If no_path_row or path_row_also_empty > 0,
-- those uris need the server to push the preview to IPFS (refreshTezosMetadataByArtwork /
-- ensureIPFSReferenceForURI) — do not invent a CID here.

-- 1 · rebuild: ipfs_uri = <path row cid> ? <query of this uri>
UPDATE ipfs_reference r
SET ipfs_uri = p.ipfs_uri || '?' || split_part(r.uri, '?', 2),
    updated_at = now()
FROM ipfs_reference p
WHERE r.ipfs_uri LIKE 'ipfs://?%'
  AND p.uri = split_part(r.uri, '?', 1)
  AND p.ipfs_uri LIKE 'ipfs://%'
  AND p.ipfs_uri NOT LIKE 'ipfs://?%'
  AND split_part(r.uri, '?', 2) <> '';
-- expect UPDATE 166

-- 2 · after: none left
SELECT count(*) AS still_broken FROM ipfs_reference WHERE ipfs_uri LIKE 'ipfs://?%';   -- expect 0

-- 3 · the tokens these feed: their on-chain TZIP-21 metadata may have been minted
--     with the broken artifactUri. List them so Hieu can check / refresh.
SELECT a.id AS token_id, a.series_id, a.preview_uri, r.ipfs_uri
FROM artworks a JOIN ipfs_reference r ON r.uri = a.preview_uri
WHERE r.updated_at >= now() - interval '5 minutes' AND r.ipfs_uri LIKE 'ipfs://%?%'
ORDER BY a.series_id, a.index;

-- ROLLBACK;  -- if the counts are off
COMMIT;
