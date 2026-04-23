-- Scenario 4b: same row as poc_08, but raw columns for JSON-boundary comparison.
SELECT
  id,
  product_sku,
  title_part,
  pros_part,
  cons_part,
  action_part
FROM poc_review_columns
WHERE id = 2;
