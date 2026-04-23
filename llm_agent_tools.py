"""
Tool implementations for agent_pipeline.py (Ollama tool calling).

Security defaults are restrictive: web client code runs only with explicit opt-in
for off-localhost URLs. The email tool logs the generated message details to stderr.
"""

from __future__ import annotations

import json
import os
import re
import sys
from html import unescape
from typing import Any
from urllib.parse import urlparse

import httpx

# --- fetch_url ---

_DEFAULT_FETCH_PREFIXES = (
    "http://127.0.0.1",
    "http://localhost",
    "https://127.0.0.1",
    "https://localhost",
)


def _fetch_allowlist_prefixes() -> tuple[str, ...]:
    raw = (os.environ.get("FETCH_URL_ALLOWLIST_PREFIXES") or "").strip()
    if not raw:
        return _DEFAULT_FETCH_PREFIXES
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return tuple(parts)


def _url_allowed_for_fetch(url: str) -> bool:
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    normalized = f"{p.scheme}://{p.netloc.split('@')[-1]}"
    for prefix in _fetch_allowlist_prefixes():
        if url.startswith(prefix) or normalized.startswith(prefix.rstrip("/")):
            return True
    return False


def tool_fetch_url(url: str) -> str:
    """GET url (http/https), return truncated text/plain-ish body. Allowlist required."""
    url = (url or "").strip()
    if not url:
        return json.dumps({"error": "url is required"})
    if not _url_allowed_for_fetch(url):
        return json.dumps(
            {
                "error": "URL not on FETCH_URL_ALLOWLIST_PREFIXES. "
                "Set env to allow (comma-separated prefixes), e.g. https://example.com for research only."
            }
        )
    max_bytes = int(os.environ.get("FETCH_URL_MAX_BYTES", "500_000").replace("_", ""))
    timeout = float(os.environ.get("FETCH_URL_TIMEOUT", "30"))
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.content[:max_bytes]
    except Exception as e:
        return json.dumps({"error": str(e)})
    # Strip tags lightly for model consumption (not security boundary)
    text = data.decode("utf-8", errors="replace")
    text = re.sub(r"(?s)<script.*?>.*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?s)<style.*?>.*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    max_chars = int(os.environ.get("FETCH_URL_MAX_CHARS", "12000").replace("_", ""))
    if len(text) > max_chars:
        text = text[: max_chars - 20] + " ...[truncated]"
    return text


# --- web_search ---

def tool_web_search(query: str) -> str:
    """
    Return short result snippets. Uses duckduckgo_search if installed; otherwise returns how to install.
    """
    query = (query or "").strip()
    if not query:
        return json.dumps({"error": "query is required"})
    if os.environ.get("AGENT_WEB_SEARCH", "1").lower() in ("0", "false", "no"):
        return json.dumps({"error": "web search disabled (AGENT_WEB_SEARCH=0)"})
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return json.dumps(
            {
                "error": "Web search needs: pip install duckduckgo-search",
            }
        )
    max_r = int(os.environ.get("WEB_SEARCH_MAX_RESULTS", "5"))
    try:
        with DDGS() as ddgs:
            hits = list(ddgs.text(query, max_results=max_r))
    except Exception as e:
        return json.dumps({"error": str(e)})
    if not hits:
        return json.dumps({"results": [], "query": query})
    out = []
    for h in hits:
        out.append(
            {
                "title": h.get("title"),
                "href": h.get("href"),
                "body": (h.get("body") or "")[:500],
            }
        )
    return json.dumps({"query": query, "results": out}, default=str)


# --- send_email (prints generated message details to terminal) ---


def tool_send_email(to: str, subject: str, body: str) -> str:
    to = (to or "").strip()
    subj = (subject or "").strip()
    body_t = (body or "").strip()
    if not to or not subj:
        return json.dumps({"error": "to and subject are required"})
    if len(body_t) > 1_000_000:
        return json.dumps({"error": "body too long"})

    # Visible in the terminal; keeps stdout for the final agent answer only
    print(
        "\n--- [send_email] message ---\n"
        f"To: {to}\n"
        f"Subject: {subj}\n"
        f"--- body ---\n{body_t}\n"
        "--- [end send_email] ---\n",
        file=sys.stderr,
        flush=True,
    )
    return json.dumps(
        {
            "ok": True,
            "to": to,
            "subject": subj,
            "note": "Email request accepted and logged to process stderr.",
        }
    )


# --- Ollama tool schema (JSON Schema in OpenAI style) ---

OLLAMA_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the public web and return a few result titles, URLs, and snippets. "
            "Use for fresh facts, documentation, or news.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "HTTP GET a single URL and return a simplified text extract. "
            "Only URLs matching FETCH_URL_ALLOWLIST_PREFIXES in the server config are allowed "
            "(default: localhost / 127.0.0.1 only).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "http(s) URL to fetch"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email request with to/subject/body and log message details to the terminal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Intended recipient address (shown in draft only)"},
                    "subject": {"type": "string"},
                    "body": {"type": "string", "description": "Plain text body"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
]

_TOOL_DISPATCH = {
    "web_search": tool_web_search,
    "fetch_url": tool_fetch_url,
    "send_email": tool_send_email,
}


def run_tool(name: str, arguments: Any) -> str:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return json.dumps({"error": f"invalid tool arguments JSON: {arguments!r}"})
    if not isinstance(arguments, dict):
        return json.dumps({"error": "tool arguments must be a JSON object"})
    fn = _TOOL_DISPATCH.get(name)
    if not fn:
        return json.dumps({"error": f"unknown tool: {name!r}"})
    try:
        return fn(**arguments)
    except TypeError as e:
        return json.dumps({"error": f"bad arguments for {name}: {e}"})

