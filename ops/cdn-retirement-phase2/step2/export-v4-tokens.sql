-- Phase-2 step 2 export: every artwork on the two V4-family contracts, with
-- the DB's current metadata doc CID (for the CID-level chain mapping check +
-- WHERE-pinned align SQL) and the ipfs_reference state of its preview/
-- thumbnail URIs (for the reference-rows step). Read-only.
--
-- Anchoring mirrors the server's own lookup (api/swap.go V3+/V4 branch:
-- Artwork.Get(ID=tokenID, ExhibitionID from exhibition_contract by address))
-- — artworks.id IS the on-chain decimal token id. Any row outside the chain
-- audits (v4_audit_truth.csv / v4_audit_crystalline.csv) is flagged by the
-- align tool as NOT_IN_AUDIT, so over-selection is caught, never updated.
--
-- Expected row counts: Truth 0xBb12686c… = 896, crystalline 0xBE0A4E26… = 9,048.
\copy (
  SELECT ec.address AS contract, ec.name AS contract_version, e.title AS exhibition,
         a.id AS token_id, a.id AS artwork_id, a.index AS edition, a.series_id,
         se.title AS series_title, se.medium,
         a.metadata->>'ipfs_cid' AS ipfs_cid,
         a.preview_uri, p.ipfs_uri AS preview_ipfs_uri,
         a.thumbnail_uri, t.ipfs_uri AS thumbnail_ipfs_uri
  FROM exhibition_contract ec
  JOIN exhibition e ON e.id = ec.exhibition_id
  JOIN artworks a ON a.exhibition_id = ec.exhibition_id
  JOIN series se ON se.id = a.series_id
  LEFT JOIN ipfs_reference p ON p.uri = a.preview_uri
  LEFT JOIN ipfs_reference t ON t.uri = a.thumbnail_uri
  WHERE lower(ec.address) IN ('0xbb12686c360e9057be3cd031140035a705e19cec',
                              '0xbe0a4e26a156b2a60cf515e86b3df9756dee1952')
  ORDER BY ec.address, a.series_id, a.index
) TO '/Users/yehboyang/status/ops/cdn-retirement-phase2/step2/v4_tokens_export.csv' CSV HEADER
