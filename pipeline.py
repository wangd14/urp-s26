#!/usr/bin/env python3
"""
SQL → JSON serialization and Ollama chat helpers, plus an optional direct CLI.
For normal use, run ``agent_pipeline.py`` (this module is shared library code).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, TextIO

import httpx
import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv()

DEFAULT_SQL = """
SELECT
  p.name AS product,
  COUNT(*) AS review_count,
  ROUND(AVG(r.rating)::numeric, 2) AS avg_rating,
  MAX(r.reviewed_at) AS latest_review_at
FROM customer_reviews r
JOIN products p ON p.id = r.product_id
GROUP BY p.name
ORDER BY avg_rating DESC, review_count DESC;
""".strip()

SYSTEM_PROMPT = (
    "You are preparing and sending a daily product review email to abc@gmail.com from PostgreSQL query results. "
    "The user message is JSON rows from a scheduled reporting query. "
    "Summarize trends in ratings and notable review themes using only that data as email-ready content. "
    "If results are truncated, mention that briefly."
)


def print_transcript(
    sql_text: str, system: str, user: str, response: str, stream: TextIO | None = None
) -> None:
    """
    Print SQL, the first-turn Ollama messages (system + user), and model output.
    Matches the two roles the API uses — no extra nested “user message” framing.
    """
    out: TextIO = stream or sys.stdout
    width = 72
    line = "=" * width

    def _block(heading: str, body: str) -> None:
        print(file=out)
        print(line, file=out)
        print(heading, file=out)
        print(line, file=out)
        print(body, file=out)
        if not body.endswith("\n"):
            print(file=out)

    _block("1. SQL QUERY (Postgres; not part of the user message)", sql_text)
    first_turn = f"System:\n{system}\n\nUser:\n{user}"
    _block("2. FIRST TURN: SYSTEM + USER (user text = result JSON only)", first_turn)
    _block("3. MODEL OUTPUT", response)


def _load_sql(path: str | None) -> str:
    if not path:
        return DEFAULT_SQL
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def _serialize_rows(rows: list[dict[str, Any]], max_rows: int, max_chars: int) -> tuple[str, bool, bool]:
    """Returns (text, rows_truncated, chars_truncated)."""
    if len(rows) > max_rows:
        rows = rows[:max_rows]
        rows_truncated = True
    else:
        rows_truncated = False

    text = json.dumps(rows, indent=2, default=str)
    if len(text) <= max_chars:
        return text, rows_truncated, False

    text = text[: max_chars - 40] + "\n... [truncated for length] ..."
    return text, rows_truncated, True


def _user_message_for_model(
    payload: str,
    *,
    num_rows_fetched: int,
    rows_truncated: bool,
    chars_truncated: bool,
    max_rows: int,
) -> str:
    """
    What we send to the model as the user turn: the query result (JSON) only, plus
    short notes if truncation was applied. The SQL is not included here; it is only
    shown in the human-readable transcript.
    """
    out = payload
    if rows_truncated:
        out = f"{out}\n\n[Only the first {max_rows} of {num_rows_fetched} rows are included.]"
    if chars_truncated:
        out = f"{out}\n[Result JSON was cut to the character cap.]"
    return out


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run SQL, send results to Ollama")
    p.add_argument(
        "--query-file",
        type=str,
        default=None,
        help="Path to a .sql file (UTF-8). If omitted, a built-in demo query is used.",
    )
    p.add_argument(
        "--max-rows",
        type=int,
        default=int(os.environ.get("MAX_RESULT_ROWS", "200")),
        help="Max rows to include in the prompt (default: env MAX_RESULT_ROWS or 200).",
    )
    p.add_argument(
        "--max-chars",
        type=int,
        default=int(os.environ.get("MAX_RESULT_CHARS", "12000")),
        help="Max characters of serialized results (default: env MAX_RESULT_CHARS or 12000).",
    )
    p.add_argument(
        "--ollama-url",
        default=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
        help="Ollama base URL (default: OLLAMA_BASE_URL or http://127.0.0.1:11434).",
    )
    p.add_argument(
        "--model",
        default=os.environ.get("OLLAMA_MODEL", "qwen2.5:14b-instruct"),
        help="Ollama model tag (default: OLLAMA_MODEL or qwen2.5:14b-instruct).",
    )
    p.add_argument(
        "--brief",
        action="store_true",
        help="Print only the model reply (default: print SQL, full prompt, then model output, clearly separated).",
    )
    return p.parse_args()


def _ollama_chat(
    base_url: str, model: str, system: str, user: str, timeout: float = 300.0
) -> str:
    url = f"{base_url}/api/chat"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json=body)
        r.raise_for_status()
        data = r.json()
    msg = data.get("message") or {}
    content = msg.get("content")
    if not content:
        raise RuntimeError(f"Unexpected Ollama response: {data!r}")
    return content


def main() -> int:
    args = _parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print(
            "DATABASE_URL is not set. Example: "
            "postgresql://poc:pocsecret@127.0.0.1:5432/pocdb",
            file=sys.stderr,
        )
        return 1

    sql = _load_sql(args.query_file)

    try:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows: list[dict[str, Any]] = list(cur.fetchall())
    except Exception as e:
        print(f"Database error: {e}", file=sys.stderr)
        return 1

    payload, rows_t, chars_t = _serialize_rows(
        rows, max_rows=args.max_rows, max_chars=args.max_chars
    )
    user_msg = _user_message_for_model(
        payload,
        num_rows_fetched=len(rows),
        rows_truncated=rows_t,
        chars_truncated=chars_t,
        max_rows=args.max_rows,
    )

    try:
        reply = _ollama_chat(
            args.ollama_url, args.model, SYSTEM_PROMPT, user_msg
        )
    except httpx.HTTPStatusError as e:
        body = (e.response.text or "").strip()
        print(f"Ollama HTTP error: {e}", file=sys.stderr)
        if body:
            print(body, file=sys.stderr)
        return 1
    except httpx.HTTPError as e:
        print(f"Ollama HTTP error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Ollama error: {e}", file=sys.stderr)
        return 1

    if args.brief:
        print(reply)
    else:
        print_transcript(sql, SYSTEM_PROMPT, user_msg, reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
