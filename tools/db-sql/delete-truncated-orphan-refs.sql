-- Delete ipfs_reference rows with a truncated (45-char) Qm CID that no artwork
-- references. Applied 2026-08-28: 9 rows, all '…/index.html' keys from 2022-12
-- software uploads whose series were re-uploaded under a new timestamp (or,
-- for OFFICE PARK and APARTMENT BLOCK, whose live rows are the '…/<ts>/' path
-- row + per-edition query rows, never the index.html key). feral-file#3435.
BEGIN;
SELECT uri, ipfs_uri FROM ipfs_reference
WHERE ipfs_uri LIKE 'ipfs://Qm%' AND ipfs_uri NOT LIKE '%?%' AND length(ipfs_uri) < 53
  AND NOT EXISTS (SELECT 1 FROM artworks a WHERE a.preview_uri = ipfs_reference.uri OR a.thumbnail_uri = ipfs_reference.uri);
DELETE FROM ipfs_reference
WHERE ipfs_uri LIKE 'ipfs://Qm%' AND ipfs_uri NOT LIKE '%?%' AND length(ipfs_uri) < 53
  AND NOT EXISTS (SELECT 1 FROM artworks a WHERE a.preview_uri = ipfs_reference.uri OR a.thumbnail_uri = ipfs_reference.uri);
SELECT count(*) AS malformed FROM ipfs_reference
WHERE ipfs_uri !~ '^ipfs://(Qm[1-9A-HJ-NP-Za-km-z]{44}|baf[a-z0-9]{50,})(\?.*)?$';   -- expect 0
COMMIT;
