-- Phase-2 step 2 export: every artwork on the six V3 contracts, with the
-- DB's metadata doc CID and the ipfs_reference state of its preview/
-- thumbnail URIs — the reference-rows input (gen-reference-sql.py) and the
-- db_cid cross-check for the V3 chain updates. Read-only. Same anchoring as
-- export-v4-tokens.sql (artworks.id = on-chain decimal token id).
-- Expected row count: ~2,476 (I KNOW 669, Peer to Peer 746, Chain Reaction
-- 600, BOOM TOWN 182, Gray Matter 171, Material Wonderland 108).
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
  WHERE lower(ec.address) IN ('0xe46a41b840176b62983fc71162dc9faeac4d9bcb',
                              '0x2a86c5466f088caebf94e071a77669bae371cd87',
                              '0xc4f0ee96676d3de800b9725eb628de1c5a0cbea1',
                              '0x6003994adeca13407e8dbee808280cc3ef2ab820',
                              '0x6e82e4b398ca4137007ba69ddd6ff699334d13b5',
                              '0x8f30722dd16bd63cf2665c383c1aef5e307b0046')
  ORDER BY ec.address, a.series_id, a.index
) TO '/Users/yehboyang/status/ops/cdn-retirement-phase2/step2/v3_tokens_export.csv' CSV HEADER
