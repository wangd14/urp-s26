-- Scenario 5: digest email citation line built from title + URL + snippet.
SELECT
  id,
  product_sku,
  source_title || ' | ' || reference_url || ' | ' || snippet AS citation_block
FROM poc_review_citation
ORDER BY id;
