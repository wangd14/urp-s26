# Reviews Digest SQL -> Agent POC

This project models a realistic workflow:

1. product reviews land in PostgreSQL
2. a scheduled SQL job selects recent ratings/review context
3. `agent_pipeline.py` sends the SQL result JSON to Ollama
4. the model returns digest-ready product insights (optionally with tool mode)

## Scenario overview

- `initdb/01_seed.sql` creates `products` and `customer_reviews`
- `initdb/02_poc_stored_injection.sql` adds lab fixture tables for query-shaping scenarios in the reviews domain
- `queries/poc_*.sql` each represent a digest query variant (joins, ordered fragments, bytea decode, URL references, etc.)

## Query reference

- `queries/poc_01_two_table_join_format.sql`: Reassembles one split review (`poc_review_head` + `poc_review_tail`) using `format()` for a targeted `review_key`.
- `queries/poc_01b_two_table_join_concat.sql`: Same split-table join pattern as `poc_01`, but uses `||` concatenation and returns all joined rows.
- `queries/poc_02_string_agg_ordered.sql`: Merges ordered text fragments from `poc_review_fragments` with `string_agg(... ORDER BY ord)` for a single review.
- `queries/poc_03_gated_assembly.sql`: Builds escalation text from `poc_low_rating_feed`, but only for low ratings (`rating <= 2`).
- `queries/poc_03b_case_masked_projection.sql`: Returns all low-rating feed rows while masking non-low-rating text via a `CASE` projection.
- `queries/poc_04_bytea_single_utf8.sql`: Decodes a single archived `bytea` review body in `poc_review_blob` with `convert_from(..., 'UTF8')`.
- `queries/poc_05_bytea_chunked_string_agg.sql`: Decodes and ordered-merges chunked `bytea` payloads from `poc_review_blob_chunks`.
- `queries/poc_06_url_source_column.sql`: Returns summary rows plus `source_url` from `poc_review_source_url` for optional second-stage fetches.
- `queries/poc_07_citation_title_url_snippet.sql`: Builds one citation string by concatenating source title, reference URL, and snippet from `poc_review_citation`.
- `queries/poc_08_horizontal_concat.sql`: Horizontally concatenates multi-column review parts from `poc_review_columns` into one merged review string.
- `queries/poc_09_horizontal_raw_columns.sql`: Returns the same `poc_review_columns` row as raw separate fields for boundary/serialization comparison.
- `queries/poc_10_rag_top_doc_chunks_merged.sql`: Simulates a simple RAG post-retrieval merge by aggregating ordered chunks from `poc_review_rag_chunks`.
- `queries/poc_11_row_json_horizontal.sql`: Emits the selected `poc_review_columns` row as a single JSON object (`row_to_json`) for shape comparison.

## Quick start

```bash
cd "/path/to/Research Proj"
docker compose up -d
docker compose exec ollama ollama pull qwen2.5:14b-instruct
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

To reseed the database fixture tables:

```bash
./seed_database.sh
```

## Run the digest pipeline

```bash
# default: single chat, no tool loop
python agent_pipeline.py --query-file queries/poc_01_two_table_join_format.sql

# optional tool mode for URL fetch / email drafting workflows
python agent_pipeline.py --query-file queries/poc_06_url_source_column.sql --tools --model qwen2.5:14b-instruct
```

Useful flags:

- `--brief` print only model output (no transcript sections)
- `--max-rows` / `--max-chars` cap serialized result size
- `--max-tool-rounds` tool-loop bound in `--tools` mode

## Tool mode contract (`--tools`)

In `--tools` mode, the pipeline enforces a strict contract for agent behavior:

- English-only output: assistant text and tool arguments must be in English.
- Required tool usage: `send_email` must be called exactly once.
- Guardrail retry: if the model returns plain text instead of tool calls, the loop injects one repair reminder and retries.
- Explicit failure: if `send_email` is missing or called more than once, the run returns an `ERROR:` message explaining the contract violation.

This is intentional so tool mode is deterministic and does not silently accept non-executed "fake tool call" text.

Default output has three sections:

1. SQL query executed
2. first turn sent to Ollama (`System` + `User`, where `User` is JSON result rows only)
3. final model output

## Batch runs

`run_agent_variants.sh` runs `agent_pipeline.py` across multiple `queries/*.sql` files.

```bash
chmod +x run_agent_variants.sh
./run_agent_variants.sh
./run_agent_variants.sh -B
./run_agent_variants.sh -t low_rating
./run_agent_variants.sh -- --model qwen2.5:3b --tools
```

## Notes

- SQL text is trusted; row values are treated as untrusted content.
- Tool mode is opt-in (`--tools`). Keep `fetch_url` allowlists strict for lab safety.
- For a clean DB reset, use `docker compose down -v` then bring stack up again.
