-- Scenario 2b: chunked review archive decoded and merged by order.
SELECT
  doc_id,
  string_agg(convert_from(chunk, 'UTF8'), '' ORDER BY ord) AS decoded_merged_review
FROM poc_review_blob_chunks
WHERE doc_id = 9
GROUP BY doc_id;
