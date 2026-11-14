import re

_PATTERNS = [
    (re.compile(r"glpat-[A-Za-z0-9_\-]{8,}"), "glpat-***"),
    (re.compile(r"sk-[A-Za-z0-9]{16,}"), "sk-***"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer ***"),
    (re.compile(r"(?i)\b(api[_-]?key|password|secret)\s*[:=]\s*\S+"), r"\1=***"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AKIA***"),
]

_DENY = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "disable the guardrails",
    "disable guardrails",
    "disable the approval",
    "reveal the system prompt",
    "drop the production database",
    "bypass approval",
)


def mask_sensitive(text: str) -> str:
    masked = text or ""
    for pattern, repl in _PATTERNS:
        masked = pattern.sub(repl, masked)
    return masked


def mask_sql_literals(sql: str) -> str:
    """Replace string and numeric SQL literals so a statement can go to the model."""
    if not sql:
        return ""
    without_strings = re.sub(r"'(?:''|[^'])*'", "?", sql)
    # Leave $1-style placeholders in place. They are not literals.
    return re.sub(r"(?<!\$)\b\d+(?:\.\d+)?\b", "?", without_strings)


def denied_reason(text: str) -> str | None:
    lowered = (text or "").lower()
    for phrase in _DENY:
        if phrase in lowered:
            return phrase
    return None
