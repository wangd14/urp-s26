-- Scenario 4a: a review spread across attributes, concatenated for digest.
SELECT
  id,
  product_sku,
  title_part || pros_part || cons_part || action_part AS merged_review
FROM poc_review_columns
WHERE id = 2;
