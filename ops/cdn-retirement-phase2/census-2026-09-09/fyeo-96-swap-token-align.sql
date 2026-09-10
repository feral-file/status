-- For Your Eyes Only #96 (exhibition 6be0bfbc-391a-40f0-bf13-6aa61c628f30,
-- series 19c097b4-c440-44e9-b6a8-eb97f3b4513a, artwork
-- 6f82d5448f0709e9dd2740dce3567bb967e31c2dd5b44e66cf0fc4d1d2b6cfbb).
--
-- The swap to Ethereum completed on 2024-05-22 (swapArtworkFromBitmark, tx
-- 0xdb369ecc79becf3c9e09319d7a9b5440d7dec1199dca080f300846b40ab54578, minted to
-- 0xF63e087a4aa3C541D2Df00418e2012a1DF89D07B) but the DB kept the Bitmark id
-- as the token id: swaps.token and the artwork's token id both hold the 64-hex
-- string 81cfe74a…bcc083 while every other completed swap on
-- FeralfileExhibitionV2 0x6DBa1302… holds the decimal uint256. On chain the
-- token id IS that hex read as uint256:
--   58715691114557290052923369262590057385049903455696195926578851682062958379139
-- (ownerOf -> 0xf63e…d07b = swaps.recipient_address; tokenURI ->
--  https://ipfs.bitmark.com/ipfs/QmRB42NjEJdqoHXGDSWmY4xk5ZhVq8sssKPChYc3WNFWYo/metadata.json,
--  which matches swaps.ipfs_cid, so only the id form is wrong).
--
-- Discipline (ops/cdn-retirement-phase2/STATUS.md): first run without COMMIT
-- as a dry run, read the counts (each UPDATE must report 1), then append COMMIT.

BEGIN;

-- 0. Column names to confirm before running the UPDATEs (the artworks token
--    column is assumed to be token_id -- check with \d artworks):
--    \d swaps
--    \d artworks

-- 1. What is there now (expect: 1 swaps row, status complete, token = hex,
--    ipfs_cid = QmRB42…; 1 artworks row with the same hex token id).
SELECT id, artwork_id, status, blockchain_type, contract_address, token, ipfs_cid,
       recipient_address, created_at, updated_at
FROM swaps
WHERE artwork_id = '6f82d5448f0709e9dd2740dce3567bb967e31c2dd5b44e66cf0fc4d1d2b6cfbb';

SELECT id, series_id, index, token_id, created_at, updated_at
FROM artworks
WHERE id = '6f82d5448f0709e9dd2740dce3567bb967e31c2dd5b44e66cf0fc4d1d2b6cfbb';

-- 2. The shape every sibling has (a completed swap on the same contract:
--    decimal token, ipfs_cid = tokenURI directory). #108 of the same exhibition:
SELECT id, artwork_id, status, token, ipfs_cid
FROM swaps
WHERE artwork_id = '46b9b2dbc9afa387620090b218a5e188c994bad0c0ae80947e60d4df8855d0f4';

-- 3. Any other completed Ethereum swap still carrying a non-decimal token?
--    (expect exactly this one row; if more come back, stop and look.)
SELECT id, artwork_id, contract_address, token
FROM swaps
WHERE status = 'complete' AND blockchain_type = 'ethereum' AND token !~ '^[0-9]+$';

-- 4. The fix: same row, same swap, decimal form of the same id.
UPDATE swaps
SET token = '58715691114557290052923369262590057385049903455696195926578851682062958379139',
    updated_at = now()
WHERE id = '69f94fe5-9d66-48bc-9015-7b57d1a4d982'
  AND artwork_id = '6f82d5448f0709e9dd2740dce3567bb967e31c2dd5b44e66cf0fc4d1d2b6cfbb'
  AND status = 'complete'
  AND lower(contract_address) = '0x6dba130221a1c39f6623908a136976686050059a'
  AND token = '81cfe74a3d62aa5b7beaaadafa8d239cfe3eacc1df12a601bccda27441bcc083'
  AND ipfs_cid = 'QmRB42NjEJdqoHXGDSWmY4xk5ZhVq8sssKPChYc3WNFWYo';
-- expect: UPDATE 1

UPDATE artworks
SET token_id = '58715691114557290052923369262590057385049903455696195926578851682062958379139',
    updated_at = now()
WHERE id = '6f82d5448f0709e9dd2740dce3567bb967e31c2dd5b44e66cf0fc4d1d2b6cfbb'
  AND token_id = '81cfe74a3d62aa5b7beaaadafa8d239cfe3eacc1df12a601bccda27441bcc083';
-- expect: UPDATE 1

-- 5. Read back: both rows now show the decimal id; the swap is otherwise unchanged.
SELECT s.token, s.ipfs_cid, a.token_id
FROM swaps s JOIN artworks a ON a.id = s.artwork_id
WHERE s.id = '69f94fe5-9d66-48bc-9015-7b57d1a4d982';

-- COMMIT;   -- append only after the dry run showed UPDATE 1 twice

-- After commit, verify through the API the census reads:
--   GET https://feralfile.com/api/artworks/6f82d5448f0709e9dd2740dce3567bb967e31c2dd5b44e66cf0fc4d1d2b6cfbb?includeActiveSwap=true&includeSuccessfulSwap=true
--   -> successfulSwap.token = 58715691114557290052923369262590057385049903455696195926578851682062958379139
-- and on chain: tokenURI(that id) = https://ipfs.bitmark.com/ipfs/QmRB42NjEJdqoHXGDSWmY4xk5ZhVq8sssKPChYc3WNFWYo/metadata.json
