-- Goal 1 check: every still-Bitmark work needs BOTH ipfs_reference rows before it
-- can be swapped (swap.GenerateMetadata errors on a missing one). Read-only.
WITH still_bitmark AS (
  SELECT a.* FROM artworks a JOIN exhibition e ON e.id = a.exhibition_id
  WHERE e.mint_blockchain = 'bitmark'
    AND NOT EXISTS (SELECT 1 FROM swaps s WHERE s.artwork_id = a.id AND s.status = 'complete')
)
SELECT count(*)                                                        AS works,
       count(*) FILTER (WHERE p.uri IS NULL)                           AS missing_preview_ref,
       count(*) FILTER (WHERE t.uri IS NULL)                           AS missing_thumbnail_ref,
       count(DISTINCT a.thumbnail_uri) FILTER (WHERE t.uri IS NULL)    AS distinct_thumbnails_to_push
FROM still_bitmark a
LEFT JOIN ipfs_reference p ON p.uri = a.preview_uri
LEFT JOIN ipfs_reference t ON t.uri = a.thumbnail_uri;
-- expect works ≈ 4,959, missing_preview_ref = 0. If missing_thumbnail_ref > 0, list them:
-- SELECT DISTINCT a.thumbnail_uri FROM still_bitmark a LEFT JOIN ipfs_reference t ON t.uri = a.thumbnail_uri WHERE t.uri IS NULL;
-- and run the server task EnsureIPFSReferenceByURI for each (pushes the file, writes the row).
