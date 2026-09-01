-- Goal 2 step 0: every Ethereum V2 token of a Bitmark-era exhibition, with its
-- current metadata directory CID and the ipfs_reference targets its new
-- metadata should use. Read-only. Filter the result against
-- migrated_bitmark_works_media_hosting_2026-08-25.csv (class != all-ipfs) for
-- the 5,903 to fix; rows with a NULL reference need EnsureIPFSReferenceByURI first.
\copy (
  SELECT ec.address AS contract, ec.name AS contract_version, e.title AS exhibition,
         s.token AS token_id, a.id AS artwork_id, a.index AS edition, a.series_id,
         s.ipfs_cid AS old_metadata_cid,
         a.preview_uri, p.ipfs_uri AS preview_ipfs_uri,
         a.thumbnail_uri, t.ipfs_uri AS thumbnail_ipfs_uri,
         se.medium
  FROM swaps s
  JOIN artworks a ON a.id = s.artwork_id
  JOIN series se ON se.id = a.series_id
  JOIN exhibition e ON e.id = a.exhibition_id
  JOIN exhibition_contract ec ON lower(ec.address) = lower(s.contract_address)
  LEFT JOIN ipfs_reference p ON p.uri = a.preview_uri
  LEFT JOIN ipfs_reference t ON t.uri = a.thumbnail_uri
  WHERE s.status = 'complete' AND s.blockchain_type = 'ethereum'
    AND e.mint_blockchain = 'bitmark'
    AND ec.name = 'FeralfileExhibitionV2'
  ORDER BY e.title, a.series_id, a.index
) TO '/Users/yehboyang/status/ops/3435-hls-fix/v2_cdn_tokens_export.csv' CSV HEADER
