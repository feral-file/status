-- filum fix, DB side — read-only export of every artwork on Truth (0xBb12686c…), 896 rows expected.
-- Gives the align generator the CURRENT ipfs_cid form (path <dir>/<tokenId> or bare CID — measured,
-- not assumed) and the overlay value that must be dropped for the 128 filum rows.
\copy (
  SELECT a.id AS token_id, a.series_id, se.title AS series_title, a.index AS edition,
         a.metadata->>'ipfs_cid' AS ipfs_cid,
         a.metadata->>'alternativePreviewURI' AS alternative_preview_uri
  FROM exhibition_contract ec
  JOIN artworks a ON a.exhibition_id = ec.exhibition_id
  JOIN series se ON se.id = a.series_id
  WHERE lower(ec.address) = '0xbb12686c360e9057be3cd031140035a705e19cec'
  ORDER BY se.title, a.index
) TO '/Users/yehboyang/status/ops/cdn-retirement-phase2/filum/truth_db_export.csv' CSV HEADER
