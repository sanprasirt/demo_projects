"""Deterministic OpenAI-compatible chat server for the demo and pytest."""

import json
import logging
import os
import re
from collections import deque

import uvicorn
from fastapi import FastAPI

from agentic_sre.scenarios import BAD_DEPLOY_SHA, BAD_DEPLOY_TAG

log = logging.getLogger("mock_llm")

BLOCK_PHRASES = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "disable the guardrails",
    "disable guardrails",
    "disable the approval",
    "reveal the system prompt",
    "drop the production database",
    "bypass approval",
)

SCRIPTS = {
    "bad-deploy": [
        ("promql_query", {"query": 'sum(rate(demo_http_requests_total{service="catalog",status=~"5.."}[1m]))'}),
        ("logql_query", {"query": '{service="catalog"} |= "NullPrice"'}),
        ("traceql_query", {"query": '{ resource.service.name = "catalog" && status = error }'}),
        ("gitlab_read", {"what": "deployments"}),
        ("get_runbook", {"runbook_id": "bad-deploy"}),
    ],
    "memory-leak": [
        ("promql_query", {"query": 'max(demo_memory_bytes{service="catalog"})'}),
        ("logql_query", {"query": '{service="catalog"} |= "leak"'}),
        ("traceql_query", {"query": '{ resource.service.name = "catalog" }'}),
        ("gitlab_read", {"what": "commits"}),
        ("get_runbook", {"runbook_id": "memory-leak"}),
    ],
    "dependency-latency": [
        (
            "promql_query",
            {
                "query": 'sum(rate(demo_dependency_latency_seconds_sum{service="checkout"}[1m])) / sum(rate(demo_dependency_latency_seconds_count{service="checkout"}[1m]))'
            },
        ),
        ("logql_query", {"query": '{service="checkout"} |= "latency"'}),
        ("traceql_query", {"query": '{ resource.service.name = "checkout" }'}),
        ("gitlab_read", {"what": "pipelines"}),
        ("get_runbook", {"runbook_id": "dependency-latency"}),
    ],
}

HYPOTHESES = {
    "bad-deploy": (
        f"Root cause: {BAD_DEPLOY_TAG} removed the null-price check. "
        f"Catalog is returning NullPrice 500s after production deploy {BAD_DEPLOY_TAG} "
        f"({BAD_DEPLOY_SHA}). The change landed on main without a review merge request."
    ),
    "memory-leak": (
        "Root cause: catalog fail mode `leak` is retaining a buffer and "
        "demo_memory_bytes is climbing. This is not a new deploy."
    ),
    "dependency-latency": (
        "Root cause: checkout's orders-db call is sleeping under fail mode `latency`. "
        "Request rate is healthy and there is no bad deploy on this path."
    ),
}


def _text(messages: list) -> str:
    parts = []
    for message in messages or []:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text", "")))
    return "\n".join(parts)


def _scenario(blob: str) -> str:
    if "ServiceMemoryHigh" in blob or "memory-leak" in blob:
        return "memory-leak"
    if "DependencyLatencyHigh" in blob or "dependency-latency" in blob:
        return "dependency-latency"
    return "bad-deploy"


def _phase(blob: str) -> str:
    match = re.search(r"PHASE=([a-z_]+)", blob)
    if match:
        return match.group(1)
    lowered = blob.lower()
    if "should the user message be blocked" in lowered or "should the message be blocked" in lowered:
        return "self_check"
    return "dialog"


def _tool_count(messages: list) -> int:
    return sum(1 for message in messages or [] if message.get("role") == "tool")


def _evidence_ids(blob: str) -> list[str]:
    return re.findall(r'"id":\s*"(e\d+)"', blob)


def decide(messages: list, tools: list | None) -> dict:
    blob = _text(messages)
    phase = _phase(blob)
    if phase == "self_check":
        # The rail prompt repeats the policy after the question. Judge only the
        # user or model text that comes before that question.
        lowered = blob.lower()
        cut = len(lowered)
        for marker in ("should the user message be blocked", "should the message be blocked"):
            idx = lowered.find(marker)
            if idx != -1:
                cut = min(cut, idx)
        subject = lowered[:cut]
        blocked = any(phrase in subject for phrase in BLOCK_PHRASES)
        return {"content": "Yes" if blocked else "No", "tool_calls": []}
    if phase == "hypothesis":
        scenario = _scenario(blob)
        ids = _evidence_ids(blob) or ["e1", "e2"]
        cites = " ".join(f"[{item}]" for item in ids[:4])
        return {"content": f"{HYPOTHESES[scenario]} {cites}", "tool_calls": []}
    if phase == "propose":
        return {
            "content": "Propose the next runbook step and wait for approval before any write.",
            "tool_calls": [],
        }
    if phase == "postmortem":
        return {
            "content": (
                "The catalog 5xx tracked the v1.4.2 deploy. "
                "After approval the revert merge request was opened and fail mode was cleared. "
                "The error rate fell and the incident can close."
            ),
            "tool_calls": [],
        }
    if phase == "investigate" and tools:
        scenario = _scenario(blob)
        script = SCRIPTS[scenario]
        index = _tool_count(messages)
        if index < len(script):
            name, arguments = script[index]
            return {
                "content": "",
                "tool_calls": [{"id": f"call_{scenario}_{index}", "name": name, "arguments": arguments}],
            }
        return {"content": "Investigation complete. Evidence is in the tool results.", "tool_calls": []}
    return {
        "content": "Acknowledged. I will investigate with read-only tools and cite evidence.",
        "tool_calls": [],
    }


def create_app() -> FastAPI:
    app = FastAPI(title="mock-llm")
    app.state.recent = deque(maxlen=20)

    @app.get("/health")
    def health():
        return {"ok": True, "service": "mock-llm"}

    @app.get("/v1/models")
    def models():
        return {"object": "list", "data": [{"id": "mock-sre", "object": "model"}]}

    @app.get("/admin/last")
    def last():
        return {"recent": list(app.state.recent)}

    @app.post("/v1/chat/completions")
    async def completions(body: dict):
        messages = body.get("messages") or []
        choice = decide(messages, body.get("tools"))
        app.state.recent.append({"phase": _phase(_text(messages)), "tools": [c["name"] for c in choice["tool_calls"]]})
        message = {"role": "assistant", "content": choice["content"] or None}
        finish = "stop"
        if choice["tool_calls"]:
            finish = "tool_calls"
            message["tool_calls"] = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {"name": call["name"], "arguments": json.dumps(call["arguments"])},
                }
                for call in choice["tool_calls"]
            ]
        return {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "model": body.get("model") or "mock-sre",
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        }

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
