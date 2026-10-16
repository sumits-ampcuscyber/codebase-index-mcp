"""Optional cheap-model answer about ONE file (or a line range), cached by content + question + model.

This is the only part of the tool that calls an LLM, and only when summarize_file is used with
GEMINI_API_KEY / GOOGLE_API_KEY or ANTHROPIC_API_KEY set. Everything else is local and free.
CODEBASE_OFFLINE=1 turns it off even when a key is present, and likely credentials are masked before any
file content is sent.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config, indexer
from . import queries
from .redaction import redact_lines

DEFAULT_MODELS = {"gemini": "gemini-2.5-flash", "anthropic": "claude-haiku-4-5"}
MAX_INPUT_CHARS = 400_000  # ~100k tokens; larger inputs must pass a line range
MAX_OUTPUT_TOKENS = 2000

SYSTEM = (
    "You answer questions about ONE source file for another coding agent that has not read it. "
    "Be concise (at most ~200 words), concrete and factual. Refer to functions/classes by name and "
    "line numbers (lines are numbered). Do not paste large code blocks. If the answer depends on code "
    "outside this file, say which names to look up next."
)

redact = redact_lines


def _offline() -> bool:
    return os.environ.get("CODEBASE_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


def _provider() -> tuple[str | None, str | None, str | None]:
    """(provider, api_key, model) from the environment, or (None, None, None)."""
    gemini = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    choice = os.environ.get("CHEAP_MODEL_PROVIDER", "").strip().lower()
    if choice == "anthropic" and anthropic_key:
        provider, key = "anthropic", anthropic_key
    elif choice == "gemini" and gemini:
        provider, key = "gemini", gemini
    elif gemini:
        provider, key = "gemini", gemini
    elif anthropic_key:
        provider, key = "anthropic", anthropic_key
    else:
        return None, None, None
    return provider, key, os.environ.get("CHEAP_MODEL") or DEFAULT_MODELS[provider]


def _ask_anthropic(key: str, model: str, prompt: str) -> str:
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("ANTHROPIC_API_KEY is set but the 'anthropic' package is not installed: "
                           "pip install anthropic")
    client = anthropic.Anthropic(api_key=key, timeout=120.0, max_retries=2)
    try:
        resp = client.messages.create(model=model, max_tokens=MAX_OUTPUT_TOKENS, system=SYSTEM,
                                      messages=[{"role": "user", "content": prompt}])
    except anthropic.AuthenticationError:
        raise RuntimeError("Anthropic rejected the API key (check ANTHROPIC_API_KEY)")
    except anthropic.RateLimitError:
        raise RuntimeError("Anthropic rate limit hit; try again shortly")
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Anthropic API error {e.status_code}: {e.message}")
    except anthropic.APIConnectionError:
        raise RuntimeError("could not reach the Anthropic API (network)")
    if resp.stop_reason == "refusal":
        raise RuntimeError("the model declined to answer this request")
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def _ask_gemini(key: str, model: str, prompt: str) -> str:
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{urllib.parse.quote(model, safe='')}:generateContent")
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": MAX_OUTPUT_TOKENS, "temperature": 0.2},
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:  # nosec B310: fixed https URL
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Gemini API error {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"could not reach the Gemini API ({e.reason})")
    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise RuntimeError(f"Gemini returned no text: {json.dumps(data)[:300]}")
    return text


def summarize_file(file: str, question: str, line_start: int = 0, line_end: int = 0) -> str:
    if _offline():
        return ("error: summarize_file is disabled by CODEBASE_OFFLINE: no code leaves this machine. Do not "
                "retry in this chat; use get_file_summary + read_symbol_source instead.")
    provider, key, model = _provider()
    if provider is None:
        return ("error: summarize_file needs GEMINI_API_KEY (or GOOGLE_API_KEY) or ANTHROPIC_API_KEY in "
                "codebase-index-mcp/.env or the MCP env block. Do not retry in this chat; use "
                "get_file_summary + read_symbol_source (or a Cursor explore subagent) instead.")
    con = indexer.db()
    rel, err = queries.resolve_indexed(con, file)  # only indexed files may leave the machine
    if err:
        return err
    data = queries.read_repo_file(rel)
    if data is None:
        return f"error: cannot read '{file}'"
    lines = data.decode("utf-8", "replace").splitlines()
    a = max(1, line_start or 1)
    b = min(len(lines), line_end or len(lines))
    masked, n_secrets = redact_lines(lines[a - 1:b])
    numbered = "\n".join(f"{i}: {ln}" for i, ln in enumerate(masked, start=a))
    tag = f"; {n_secrets} likely secret{'s' if n_secrets != 1 else ''} masked before sending" if n_secrets else ""
    if len(numbered) > MAX_INPUT_CHARS:
        return (f"error: {rel} lines {a}-{b} is too large for one cheap-model call "
                f"(~{len(numbered) // 4:,} tokens). Pass line_start/line_end (see get_file_summary for ranges).")
    question = (question or "What does this file do?").strip()
    if len(question) > 4000:
        return "error: question is too long (maximum 4000 characters)"
    key_hash = hashlib.sha256(f"{provider}|{model}|{rel}|{a}-{b}|{question}|".encode("utf-8")
                              + hashlib.sha256(numbered.encode("utf-8")).digest()).hexdigest()
    now = time.time()
    ttl = config.SUMMARY_CACHE_TTL_SECONDS
    if ttl > 0:
        con.execute("DELETE FROM summary_cache WHERE created < ?", (now - ttl,))
        hit = con.execute("SELECT answer FROM summary_cache WHERE key=? AND created >= ?",
                          (key_hash, now - ttl)).fetchone()
    else:
        con.execute("DELETE FROM summary_cache")
        hit = None
    con.commit()
    if hit:
        return f"[cached {model}{tag}] {hit['answer']}"
    prompt = f"File: {rel} (lines {a}-{b} of {len(lines)})\nQuestion: {question}\n\n{numbered}"
    try:
        answer = _ask_anthropic(key, model, prompt) if provider == "anthropic" else _ask_gemini(key, model, prompt)
    except RuntimeError as e:
        return f"error: {e}"
    if ttl > 0:
        con.execute("INSERT OR REPLACE INTO summary_cache(key, answer, model, created) VALUES(?,?,?,?)",
                    (key_hash, answer, model, now))
        con.commit()
    return f"[{model}{tag}] {answer}"
