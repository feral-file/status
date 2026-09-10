-- Applied 2026-09-04 (back-office DB, psql, two-step BEGIN/dry-run then COMMIT).
-- Freezes OpenSea grouping fields on every series that has an Ethereum contract,
-- writing exactly the value api/swap.go was already deriving at request time
-- (verified against the live API before applying: uuid 439/442 equal, 0 mismatch,
-- 3 series with no on-chain token n/a; name 283/283 equal). Zero change for
-- OpenSea; removes the drift (series-row rebuild → new uuid; alias/title edit →
-- new name) that produced the Infinite Entropy duplicate.
-- Pre-freeze snapshot: collection_uuid_audit.csv (280 FALLBACK / 162 FROZEN).
-- Post-freeze deliverable sent to OpenSea: opensea_collection_mapping_2026-09-04-2.csv
-- (440 series → 294 collections).

-- 1) collectionUUID := series.id where unset. Expected UPDATE 280.
BEGIN;
UPDATE series s
SET metadata   = jsonb_set(coalesce(s.metadata,'{}'::jsonb),
                           '{collectionUUID}', to_jsonb(s.id::text)),
    updated_at = now()
WHERE COALESCE(s.metadata->>'collectionUUID','') = ''
  AND EXISTS (SELECT 1 FROM exhibition_contract ec
              WHERE ec.exhibition_id = s.exhibition_id
                AND ec.blockchain_type = 'ethereum');
COMMIT;

-- 2) collectionName := "<title> by <PrettyAlias(artist)>" where unset.
--    PrettyAlias = alias with <A2P> / _tez / _custody stripped (same regex as Go).
--    Expected UPDATE 283 (preflight count must match, else ROLLBACK).
BEGIN;
UPDATE series s
SET metadata   = jsonb_set(coalesce(s.metadata,'{}'::jsonb), '{collectionName}',
                   to_jsonb(s.title || ' by ' ||
                            regexp_replace(aa.alias, '<A2P>|_tez|_custody', '', 'g'))),
    updated_at = now()
FROM alumni_accounts aa
WHERE aa.id = s.artist_alumni_account_id
  AND COALESCE(s.metadata->>'collectionName','') = ''
  AND EXISTS (SELECT 1 FROM exhibition_contract ec
              WHERE ec.exhibition_id = s.exhibition_id
                AND ec.blockchain_type = 'ethereum');
COMMIT;

-- Verify afterwards (expect FROZEN = all, FALLBACK = 0 for both fields):
-- SELECT CASE WHEN COALESCE(metadata->>'collectionUUID','') = '' THEN 'FALLBACK' ELSE 'FROZEN' END, count(*)
-- FROM series s WHERE EXISTS (SELECT 1 FROM exhibition_contract ec
--   WHERE ec.exhibition_id = s.exhibition_id AND ec.blockchain_type = 'ethereum') GROUP BY 1;
