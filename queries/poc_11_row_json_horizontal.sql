-- Scenario 4 (optional compare): one JSON object for the same row used in poc_08/poc_09.
SELECT row_to_json(t) AS row_json
FROM (SELECT * FROM poc_review_columns WHERE id = 2) AS t;
