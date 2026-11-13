"""Colang actions. Importing this module registers them with NeMo."""

from agentic_sre.agent.guardrails import ExecutionGuard
from agentic_sre.masking import mask_sensitive

try:
    from nemoguardrails.actions import action
except Exception:  # pragma: no cover - import happens when NeMo is installed
    def action(*args, **kwargs):  # type: ignore
        def wrap(fn):
            return fn
        return wrap


@action(name="mask_sensitive_text")
def mask_sensitive_text(user_message: str = "") -> str:
    return mask_sensitive(user_message)


@action(name="execution_guard")
def execution_guard(tool_name: str = "", approved: bool = False) -> bool:
    record = {"approved": bool(approved), "tool": tool_name} if approved else None
    return ExecutionGuard.from_file().check(tool_name, record).allowed
