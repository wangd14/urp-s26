-- Scenario 1c: include only low-rating reviews for escalation digest.
SELECT
  product_sku,
  rating,
  p1 || p2 AS escalation_text,
  team
FROM poc_low_rating_feed
WHERE rating <= 2
ORDER BY rating ASC, product_sku;
