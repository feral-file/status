-- Phase-2 step 2 follow-up: the per-ARTWORK alternativePreviewURI overlay
-- (api/swap.go captures art.Metadata.AlternativePreviewURI and overwrites
-- animation_url after the doc fetch — series-level was checked and is null;
-- artwork-level is the suspected source of Truth's 128 CDN rows). Read-only.
-- Expected: filum's 128 rows carry previews/71e2bed5…/1706081014/… ; the
-- interesting unknown is whether ANY crystalline row carries one too.
\copy (
  SELECT ec.address AS contract, se.title AS series_title, a.id AS token_id,
         a.metadata->>'alternativePreviewURI' AS alternative_preview_uri
  FROM exhibition_contract ec
  JOIN artworks a ON a.exhibition_id = ec.exhibition_id
  JOIN series se ON se.id = a.series_id
  WHERE lower(ec.address) IN ('0xbb12686c360e9057be3cd031140035a705e19cec',
                              '0xbe0a4e26a156b2a60cf515e86b3df9756dee1952')
    AND a.metadata->>'alternativePreviewURI' IS NOT NULL
  ORDER BY ec.address, se.title, a.index
) TO '/Users/yehboyang/status/ops/cdn-retirement-phase2/step2/v4_overlay_export.csv' CSV HEADER
