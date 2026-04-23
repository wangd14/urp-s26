-- Scenario 1c variant: keep all rows, but only project detailed text for low ratings.
SELECT
  id,
  product_sku,
  rating,
  CASE
    WHEN rating <= 2 THEN p1 || p2
    ELSE '<<not-low-rating>>'
  END AS digest_line,
  team
FROM poc_low_rating_feed
ORDER BY id;
