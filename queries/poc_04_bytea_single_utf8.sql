-- Scenario 2a: archived review body stored as bytea, decoded in SQL.
SELECT
  id,
  review_key,
  convert_from(body, 'UTF8') AS decoded_review
FROM poc_review_blob
WHERE review_key = 'ARCH-2';
