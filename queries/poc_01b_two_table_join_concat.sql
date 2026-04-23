-- Scenario 1a variant: same review split, assembled with ||.
SELECT
  h.review_key,
  h.product_sku,
  h.head_text || t.tail_text AS assembled_review
FROM poc_review_head AS h
JOIN poc_review_tail AS t ON h.review_key = t.review_key
ORDER BY h.review_key;
