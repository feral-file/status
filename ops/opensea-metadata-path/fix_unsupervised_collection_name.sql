-- Set series.metadata.collectionName for the 3 Refik Anadol "Unsupervised — Burned"
-- series whose collectionName is an empty string, so the FF API
-- (GET /api/contracts/<contract>/tokens/<id>) emits `collection_name` again.
-- Values copied verbatim from the names OpenSea currently displays (README.md),
-- so the collection name does not change when OpenSea switches to the API.
-- Context: ops/opensea-metadata-path/README.md

-- 1) inspect current values
SELECT id, title, metadata->>'collectionName' AS collection_name, metadata->>'collectionUUID' AS collection_uuid
FROM series
WHERE id IN ('72b1a11a-16da-4550-aa2c-7f197a219ae8',
             'f8d29291-cac7-480b-aacd-05de41d1a1ae',
             'aac17bb5-3377-4e4d-92bd-3767881bfba7');

-- 2) update (guarded: only rows whose collectionName is still empty)
BEGIN;

UPDATE series
SET metadata = metadata || jsonb_build_object('collectionName', 'Unsupervised - Burned - Machine Hallucinations - MoMA Dreams By Refik Anadol'),
    updated_at = now()
WHERE id = '72b1a11a-16da-4550-aa2c-7f197a219ae8' AND coalesce(metadata->>'collectionName', '') = '';

UPDATE series
SET metadata = metadata || jsonb_build_object('collectionName', 'Unsupervised - Burned - Data Universe - MoMA - 2D by Refik Anadol'),
    updated_at = now()
WHERE id = 'f8d29291-cac7-480b-aacd-05de41d1a1ae' AND coalesce(metadata->>'collectionName', '') = '';

UPDATE series
SET metadata = metadata || jsonb_build_object('collectionName', 'Unsupervised - Burned - Data Universe - MoMA - 3D by Refik Anadol'),
    updated_at = now()
WHERE id = 'aac17bb5-3377-4e4d-92bd-3767881bfba7' AND coalesce(metadata->>'collectionName', '') = '';

-- 3) verify: expect 3 rows, all non-empty
SELECT id, title, metadata->>'collectionName' AS collection_name
FROM series
WHERE id IN ('72b1a11a-16da-4550-aa2c-7f197a219ae8',
             'f8d29291-cac7-480b-aacd-05de41d1a1ae',
             'aac17bb5-3377-4e4d-92bd-3767881bfba7');

COMMIT;  -- or ROLLBACK if the verify output is not what you expect

-- 4) after commit, confirm via the public API (should now include collection_name):
--   curl -s https://feralfile.com/api/contracts/0x9D6c8e4B348999A69eE24285cd81226f4628e8F8/tokens/72683907607289245948376378937398657013536021870223758380494556672121413187268 | jq .collection_name
--   curl -s https://feralfile.com/api/contracts/0x559fE9Fe5E2DAE7A7ae5766457096E6d7C647A46/tokens/89970703136813096194386978740263577426008641841447607440390967327466404095975 | jq .collection_name
--   curl -s https://feralfile.com/api/contracts/0xc490888997d65df70FE69f33BA3bf7C8D12989CF/tokens/44698415037170023611077639980855462881371582800501602828429077410131151838137 | jq .collection_name
