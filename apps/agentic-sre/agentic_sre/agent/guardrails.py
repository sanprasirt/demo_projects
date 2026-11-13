import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from agentic_sre.masking import denied_reason, mask_sensitive
from agentic_sre.paths import GUARDRAILS

log = logging.getLogger("agentic_sre.guardrails")


@dataclass
class RailResult:
    allowed: bool
    text: str
    reason: str = ""


class ExecutionGuard:
    """Allowlist plus an approval record for every write. Default is deny."""

    def __init__(self, policy: dict):
        self.default = policy.get("default", "deny")
        self.tools = dict(policy.get("tools") or {})

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "ExecutionGuard":
        file = Path(path or (GUARDRAILS / "allowlist.yml"))
        return cls(yaml.safe_load(file.read_text(encoding="utf-8")))

    def check(self, tool_name: str, approval: dict | None) -> RailResult:
        kind = self.tools.get(tool_name)
        if kind is None:
            return RailResult(False, tool_name, f"{tool_name} is not on the allowlist")
        if kind == "read":
            return RailResult(True, tool_name, "read-only")
        if kind != "write":
            return RailResult(False, tool_name, f"{tool_name} has unknown kind {kind}")
        if not approval or not approval.get("approved"):
            return RailResult(False, tool_name, "write blocked pending approval")
        if approval.get("tool") != tool_name:
            return RailResult(False, tool_name, "approval record is for a different tool")
        return RailResult(True, tool_name, "approved write")


class Guardrails:
    def __init__(self, *, base_url: str, model: str, api_key: str, nemo_dir: str, enable_nemo: bool):
        self.execution = ExecutionGuard.from_file()
        self.rails = None
        self.nemo_error = ""
        if enable_nemo:
            self.rails = self._load(base_url, model, api_key, nemo_dir)

    def _load(self, base_url: str, model: str, api_key: str, nemo_dir: str):
        try:
            from nemoguardrails import LLMRails, RailsConfig

            from agentic_sre.agent.nemo_actions import execution_guard, mask_sensitive_text

            config = RailsConfig.from_path(nemo_dir)
            for entry in config.models:
                if entry.engine == "openai":
                    entry.model = model
                    entry.parameters["base_url"] = base_url
                    entry.parameters["api_key"] = api_key
            rails = LLMRails(config)
            rails.register_action(mask_sensitive_text, name="mask_sensitive_text")
            rails.register_action(execution_guard, name="execution_guard")
            return rails
        except Exception as exc:
            self.nemo_error = str(exc)
            log.exception("NeMo Guardrails failed to load")
            return None

    def check_input(self, text: str) -> RailResult:
        masked = mask_sensitive(text)
        phrase = denied_reason(masked)
        if phrase:
            return RailResult(False, masked, f"input rail denied: {phrase}")
        if self.rails is None:
            return RailResult(True, masked, "nemo skipped")
        try:
            reply = self.rails.generate(messages=[{"role": "user", "content": masked}])
        except Exception as exc:
            log.exception("input rail call failed")
            return RailResult(True, masked, f"nemo input error: {exc}")
        content = reply.get("content", "") if isinstance(reply, dict) else str(reply)
        if "BLOCKED_BY_RAIL" in content:
            return RailResult(False, masked, "self check input")
        return RailResult(True, masked, "self check input passed")

    def check_output(self, text: str) -> RailResult:
        masked = mask_sensitive(text)
        if self.rails is None:
            return RailResult(True, masked, "nemo skipped")
        try:
            reply = self.rails.generate(
                messages=[
                    {"role": "user", "content": "Review the drafted incident note."},
                    {"role": "assistant", "content": masked},
                    {"role": "user", "content": "Is the drafted note safe to post to the incident channel?"},
                ]
            )
        except Exception as exc:
            log.exception("output rail call failed")
            return RailResult(True, masked, f"nemo output error: {exc}")
        content = reply.get("content", "") if isinstance(reply, dict) else str(reply)
        if "BLOCKED_BY_RAIL" in content:
            return RailResult(False, masked, "self check output")
        return RailResult(True, masked, "self check output passed")

    def check_tool(self, tool_name: str, approval: dict | None) -> RailResult:
        return self.execution.check(tool_name, approval)
