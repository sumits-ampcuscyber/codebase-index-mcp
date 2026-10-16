"""Small, dependency-free secret redaction helpers shared by indexing and optional LLM calls."""
from __future__ import annotations

import re

_SECRET_NAME_RE = re.compile(
    r"(?:password|passwd|pwd|secret|token|api[-_]?key|access[-_]?key|private[-_]?key|"
    r"client[-_]?secret|authorization|authentication|credential|cookie|session[-_]?token)$",
    re.IGNORECASE,
)
_SECRET_RES = [re.compile(p) for p in (
    r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    r"\bgh[pousr]_[A-Za-z0-9]{36,}\b", r"\bgithub_pat_\w{22,}",
    r"\bxox[abposr]-[A-Za-z0-9-]{10,}",
    r"\bAIza[0-9A-Za-z_-]{35}",
    r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}",
    r"\b[rs]k_live_[0-9A-Za-z]{20,}",
    r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}",
)]
_URL_CRED_RE = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^/\s:@]+:)([^@\s/]+)(@)", re.IGNORECASE)
_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z0-9 ]*PRIVATE KEY-----")
_FIELD_RE = re.compile(r"(?i)^(?P<indent>\s*)(?P<key>[\"']?[^\"':=\s]+[\"']?)\s*(?P<sep>[:=])\s*(?P<value>.*)$")


def is_sensitive_name(name: str | None) -> bool:
    """Whether a key/path segment looks like it contains a credential."""
    if not name:
        return False
    for segment in re.split(r"[./\\]+", name):
        segment = segment.strip(" \t\"'[]{}").replace("-", "_").lower()
        if not segment:
            continue
        if _SECRET_NAME_RE.fullmatch(segment) or any(segment.endswith(suffix) for suffix in (
                "_password", "_secret", "_token", "_api_key", "_access_key", "_private_key")):
            return True
    return False


def _redact_field(line: str) -> tuple[str, int] | None:
    match = _FIELD_RE.match(line)
    if match is None or not is_sensitive_name(match.group("key")):
        return None
    value = match.group("value")
    comment = ""
    body = value
    hash_pos = value.find(" #")
    if hash_pos >= 0:
        body, comment = value[:hash_pos], value[hash_pos:]
    comma = "," if body.rstrip().endswith(",") else ""
    return (f"{match.group('indent')}{match.group('key')}{match.group('sep')} <REDACTED>{comma}{comment}", 1)


def redact_lines(lines: list[str]) -> tuple[list[str], int]:
    """Mask likely credentials while preserving line count and useful surrounding structure."""
    out, n, in_pem = [], 0, False
    for line in lines:
        if in_pem or _PEM_BEGIN.search(line):
            n += int(not in_pem)
            in_pem = not _PEM_END.search(line)
            out.append("[REDACTED private key]")
            continue
        field = _redact_field(line)
        if field is not None:
            line, count = field
            n += count
        for rx in _SECRET_RES:
            line, count = rx.subn("[REDACTED]", line)
            n += count
        line, count = _URL_CRED_RE.subn(r"\1[REDACTED]\3", line)
        n += count
        out.append(line)
    return out, n


def config_value_preview(name: str, parent: str | None, raw: str) -> str:
    """Keep useful safe config values, but never persist obvious secret fields in the index."""
    path = f"{parent}.{name}" if parent else name
    parent_parts = {part.lower() for part in re.split(r"[./\\]+", parent or "") if part}
    if is_sensitive_name(path) or (name.lower() == "value"
                                   and parent_parts.intersection({"env", "environment", "variables"})):
        return "<redacted>"
    compact = " ".join(raw.split())
    if not compact:
        return ""
    if "\n" in raw or compact.startswith(("{", "[")):
        return "<structured value>"
    _, count = redact_lines([f"{name}: {compact}"])
    if count:
        return "<redacted>"
    return compact[:160]
