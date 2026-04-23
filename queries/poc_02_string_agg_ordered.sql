-- Scenario 1b: ordered review fragments merged into one digest sentence.
SELECT
  review_id,
  string_agg(frag, '' ORDER BY ord) AS merged_review
FROM poc_review_fragments
WHERE review_id = 77
GROUP BY review_id;
