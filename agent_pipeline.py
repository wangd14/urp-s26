#!/usr/bin/env python3
"""
Run SQL, then Ollama. By default: one chat with a data-only system prompt (no tool loop).
Pass --tools for web_search, fetch_url, send_email (see llm_agent_tools.py, allowlisted fetch).
For tool mode, use a model that supports Ollama tool calling; tiny models are unreliable.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import httpx
import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from llm_agent_tools import OLLAMA_TOOLS, run_tool
from pipeline import (
    _load_sql,
    _serialize_rows,
    _user_message_for_model,
    print_transcript,
)

load_dotenv()

# Single-turn mode (default): reviews digest from DB JSON only.
SIMPLE_SYSTEM_PROMPT = (
    "You are preparing and sending a daily product-ratings and reviews email to abc@gmail.com from trusted SQL output. "
    "The user message is JSON rows from that SQL query. Be concise and business-facing. "
    "Your task is to produce email-ready content for the daily product review. "
    "Respond in English only. "
    "Answer only from the JSON. If something is missing, say you cannot infer it. "
    "Do not claim to run shell commands, install packages, or use web/search tools."
)

# Tool-loop mode (`--tools`): Ollama may call web_search, fetch_url, send_email.
AGENT_SYSTEM_PROMPT = (
    "You are a product-insights assistant with tools: web_search, fetch_url, send_email. "
    "Primary task: send a daily product review email to abc@gmail.com using database JSON rows. "
    "Call send_email exactly once with to=abc@gmail.com and a concise digest subject/body grounded in the provided data. "
    "Use English only for all assistant text and all tool arguments. "
    "Use tools only when clearly needed (for example, fetching an allowlisted source URL included in the data). "
    "For fetch_url, only same-origin or allowlisted hosts will work. "
    "Respect tool errors. Do not fabricate tool output. "
    "Never claim to install software or run pip; either return grounded analysis from DB JSON or report actual tool results/errors."
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run SQL, then Ollama agent with web/search/email tools (allowlisted)"
    )
    p.add_argument("--query-file", type=str, default=None, help="Path to a .sql file (UTF-8).")
    p.add_argument(
        "--max-rows",
        type=int,
        default=int(os.environ.get("MAX_RESULT_ROWS", "200")),
    )
    p.add_argument(
        "--max-chars",
        type=int,
        default=int(os.environ.get("MAX_RESULT_CHARS", "12000")),
    )
    p.add_argument(
        "--ollama-url",
        default=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
    )
    p.add_argument(
        "--model",
        default=os.environ.get("OLLAMA_MODEL", "qwen2.5:14b-instruct"),
        help="Model with tool support (default OLLAMA_MODEL or qwen2.5:14b-instruct).",
    )
    p.add_argument(
        "--max-tool-rounds",
        type=int,
        default=int(os.environ.get("AGENT_MAX_TOOL_ROUNDS", "8")),
        help="Max assistant→tool loop iterations (default 8).",
    )
    p.add_argument(
        "--tools",
        action="store_true",
        help="Enable the Ollama tool loop (web_search, fetch_url, send_email). "
        "Default: one chat with a data-only system prompt (no tool definitions) — use that for this repo unless you need tools.",
    )
    p.add_argument(
        "--brief",
        action="store_true",
        help="Print only the final model reply (default: print SQL, full prompt, then model output, clearly separated).",
    )
    return p.parse_args()


def _ollama_chat_with_tools(
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    timeout: float = 300.0,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/chat"
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if tools is not None:
        body["tools"] = tools
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json=body)
        r.raise_for_status()
        return r.json()


def _append_assistant_message(
    out_messages: list[dict[str, Any]], data: dict[str, Any]
) -> None:
    msg = data.get("message") or {}
    entry: dict[str, Any] = {
        "role": "assistant",
        "content": msg.get("content") or "",
    }
    tcs = msg.get("tool_calls")
    if tcs:
        entry["tool_calls"] = tcs
    out_messages.append(entry)


def _run_tool_loop(
    base_url: str, model: str, messages: list[dict[str, Any]], max_rounds: int
) -> str:
    send_email_calls = 0
    repair_prompt_used = False
    for _ in range(max_rounds):
        data = _ollama_chat_with_tools(base_url, model, messages, OLLAMA_TOOLS)
        msg = data.get("message") or {}
        content = (msg.get("content") or "").strip()
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            if send_email_calls == 1:
                return content or "(empty reply)"
            if not repair_prompt_used:
                repair_prompt_used = True
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Policy reminder: you must call send_email exactly once in this run. "
                            "Do not return plain-text JSON that looks like a tool call. "
                            "Emit a structured tool call now."
                        ),
                    }
                )
                continue
            return (
                "ERROR: required tool contract not satisfied; model ended without "
                "calling send_email exactly once."
            )

        _append_assistant_message(messages, data)

        for tc in tool_calls:
            fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
            name = fn.get("name")
            if not name:
                continue
            if name == "send_email":
                send_email_calls += 1
                if send_email_calls > 1:
                    return (
                        "ERROR: required tool contract violated; send_email was "
                        "called more than once."
                    )
            args = fn.get("arguments", {})
            result = run_tool(name, args)
            # Ollama expects tool name on tool messages; content is string
            tool_msg: dict[str, Any] = {
                "role": "tool",
                "content": result if isinstance(result, str) else str(result),
                "tool_name": name,
            }
            messages.append(tool_msg)

    if send_email_calls == 1:
        return f"(stopped after {max_rounds} tool rounds; increase --max-tool-rounds)"
    return (
        f"ERROR: required tool contract not satisfied after {max_rounds} rounds; "
        "send_email must be called exactly once."
    )


def _run_chat_no_tools(
    base_url: str, model: str, system: str, user: str, timeout: float = 300.0
) -> str:
    url = f"{base_url.rstrip('/')}/api/chat"
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
    c = msg.get("content")
    if not c:
        raise RuntimeError(f"Unexpected Ollama response: {data!r}")
    return c


def main() -> int:
    args = _parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print(
            "DATABASE_URL is not set. Example: postgresql://poc:pocsecret@127.0.0.1:5432/pocdb",
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

    if not args.tools:
        try:
            reply = _run_chat_no_tools(
                args.ollama_url, args.model, SIMPLE_SYSTEM_PROMPT, user_msg
            )
        except httpx.HTTPStatusError as e:
            print(f"Ollama HTTP error: {e}", file=sys.stderr)
            if (e.response.text or "").strip():
                print(e.response.text, file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Ollama error: {e}", file=sys.stderr)
            return 1
        if args.brief:
            print(reply)
        else:
            print_transcript(sql, SIMPLE_SYSTEM_PROMPT, user_msg, reply)
        return 0

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    try:
        reply = _run_tool_loop(
            args.ollama_url, args.model, messages, max_rounds=args.max_tool_rounds
        )
    except httpx.HTTPStatusError as e:
        print(f"Ollama HTTP error: {e}", file=sys.stderr)
        if (e.response.text or "").strip():
            print(e.response.text, file=sys.stderr)
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
        print(
            "Note: Tool mode is on: Ollama also receives tool-calling and tool-output messages "
            "in later turns; only the first user message above is the SQL result JSON.\n",
            file=sys.stderr,
        )
        print_transcript(sql, AGENT_SYSTEM_PROMPT, user_msg, reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
