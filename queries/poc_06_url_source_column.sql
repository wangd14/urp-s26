-- Scenario 3: source URL returned for optional second-stage review lookup.
SELECT
  id,
  product_sku,
  short_summary,
  source_url
FROM poc_review_source_url
ORDER BY id;
