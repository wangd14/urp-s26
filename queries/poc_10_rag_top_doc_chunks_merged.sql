-- Scenario 6: toy retrieval merge for complaint-heavy review chunks.
SELECT
  doc_id,
  string_agg(chunk_text, ' ' ORDER BY chunk_ord) AS merged_chunks
FROM poc_review_rag_chunks
WHERE doc_id = 202
GROUP BY doc_id;
