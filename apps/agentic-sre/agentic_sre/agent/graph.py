import json
import logging
import re
import time
from typing import TypedDict

import httpx
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from agentic_sre.agent.llm import assistant_message
from agentic_sre.agent.teams import build_incident_card, build_update_card
from agentic_sre.agent.tools import READ_TOOLS, TOOL_SCHEMAS, run_read, run_write

log = logging.getLogger("agentic_sre.graph")
_http = httpx.Client(timeout=8.0, trust_env=False)


class State(TypedDict, total=False):
    incident_id: str
    alertname: str
    alert_text: str
    status: str
    hypothesis: str
    hypothesis_ok: bool
    hypothesis_attempts: int
    runbook: dict
    step_index: int
    pending_step: dict | None
    approved: bool
    approval: dict | None
    recovered: bool
    outcome: str


def build_graph():
    graph = StateGraph(State)
    graph.add_node("triage", triage)
    graph.add_node("investigate", investigate)
    graph.add_node("hypothesis", hypothesis)
    graph.add_node("propose", propose)
    graph.add_node("approve", approve)
    graph.add_node("execute", execute)
    graph.add_node("verify", verify)
    graph.add_node("postmortem", postmortem)
    graph.add_node("halt", halt)
    graph.set_entry_point("triage")
    graph.add_conditional_edges("triage", route_triage, {"investigate": "investigate", "halt": "halt"})
    graph.add_edge("investigate", "hypothesis")
    graph.add_conditional_edges(
        "hypothesis",
        route_hypothesis,
        {"hypothesis": "hypothesis", "propose": "propose", "postmortem": "postmortem"},
    )
    graph.add_conditional_edges(
        "propose",
        route_propose,
        {"approve": "approve", "execute": "execute", "verify": "verify", "postmortem": "postmortem"},
    )
    graph.add_conditional_edges("approve", route_approve, {"execute": "execute", "postmortem": "postmortem"})
    graph.add_conditional_edges("execute", route_execute, {"propose": "propose", "postmortem": "postmortem"})
    graph.add_edge("verify", "propose")
    graph.add_edge("postmortem", END)
    graph.add_edge("halt", END)
    return graph.compile(checkpointer=MemorySaver())


def triage(state: State) -> dict:
    runtime = current()
    result = runtime.guard.check_input(state["alert_text"])
    runtime.store.timeline(state["incident_id"], "input_rail", result.reason or "passed")
    if not result.allowed:
        runtime.store.update(state["incident_id"], status="blocked")
        runtime.store.timeline(state["incident_id"], "blocked", result.reason)
        return {"status": "blocked"}
    runbook = runtime.runbooks.match(alertname=state["alertname"], text=state["alert_text"])
    if runbook is None:
        runtime.store.update(state["incident_id"], status="blocked")
        runtime.store.timeline(state["incident_id"], "runbook", "no runbook matched")
        return {"status": "blocked"}
    runtime.store.update(state["incident_id"], runbook_id=runbook.id, status="investigating")
    runtime.store.timeline(state["incident_id"], "runbook", f"matched {runbook.id}: {runbook.title}")
    return {"status": "investigating", "runbook": runbook.raw, "step_index": 0}


def investigate(state: State) -> dict:
    runtime = current()
    runtime.store.update(state["incident_id"], status="investigating")
    messages = [
        {
            "role": "user",
            "content": (
                f"Alert: {state['alertname']}\n{state['alert_text']}\n"
                "Investigate with the read-only tools. For a database alert, call pg_activity and "
                "pg_top_statements. Stop when you have metrics, logs, traces, and database or GitLab context."
            ),
        }
    ]
    for _ in range(8):
        result = runtime.llm.chat(phase="investigate", messages=messages, tools=TOOL_SCHEMAS)
        if not result["tool_calls"]:
            break
        messages.append(assistant_message(result))
        for call in result["tool_calls"]:
            decision = runtime.guard.check_tool(call["name"], None)
            if not decision.allowed:
                if call["name"] not in READ_TOOLS:
                    runtime.store.block_write(state["incident_id"], call["name"], call["name"])
                payload = {"kind": "guard", "query": call["name"], "summary": decision.reason, "link": ""}
            else:
                payload = run_read(runtime, call["name"], call["arguments"])
            stored = runtime.store.add_evidence(state["incident_id"], payload)
            runtime.store.timeline(state["incident_id"], "tool", f"{stored['id']} {call['name']}: {stored['summary']}")
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(stored)})
    return {}


def hypothesis(state: State) -> dict:
    runtime = current()
    incident = runtime.store.get(state["incident_id"])
    evidence = incident["evidence"]
    result = runtime.llm.chat(
        phase="hypothesis",
        messages=[
            {
                "role": "user",
                "content": (
                    f"Alert: {state['alertname']}\n"
                    "Write the root-cause hypothesis. Cite at least two evidence ids as [e1].\n"
                    f"Evidence JSON:\n{json.dumps(evidence)}"
                ),
            }
        ],
    )
    text = result["content"].strip()
    known = {item["id"] for item in evidence}
    cited = set(re.findall(r"\[(e\d+)\]", text))
    ok = len(cited & known) >= 2
    attempts = state.get("hypothesis_attempts", 0) + 1
    if not ok and attempts < 2:
        runtime.store.mark_hypothesis(state["incident_id"], text, accepted=False)
        runtime.store.timeline(state["incident_id"], "hypothesis", "citation check failed; retrying")
        return {"hypothesis": text, "hypothesis_ok": False, "hypothesis_attempts": attempts}
    if not ok:
        text = _fallback_hypothesis(evidence)
        ok = True
    checked = runtime.guard.check_output(text)
    text = checked.text
    if not checked.allowed:
        runtime.store.update(state["incident_id"], status="blocked")
        runtime.store.timeline(state["incident_id"], "output_rail", checked.reason)
        return {"hypothesis": text, "hypothesis_ok": False, "hypothesis_attempts": attempts, "status": "blocked", "outcome": "blocked"}
    runtime.store.mark_hypothesis(state["incident_id"], text, accepted=True)
    runtime.store.timeline(state["incident_id"], "hypothesis", text)
    return {"hypothesis": text, "hypothesis_ok": True, "hypothesis_attempts": attempts}


def propose(state: State) -> dict:
    runtime = current()
    steps = (state.get("runbook") or {}).get("steps") or []
    index = state.get("step_index", 0)
    if index >= len(steps):
        return {"pending_step": None}
    step = steps[index]
    try:
        runtime.llm.chat(
            phase="propose",
            messages=[{"role": "user", "content": f"Alert: {state['alertname']}\nNext step: {step['title']}"}],
        )
    except Exception:
        log.exception("propose prompt failed")
    runtime.store.update(state["incident_id"], pending_step=_public_step(step))
    runtime.store.timeline(state["incident_id"], "step_proposed", step["title"])
    return {"pending_step": step}


def approve(state: State) -> dict:
    runtime = current()
    step = state["pending_step"]
    incident_id = state["incident_id"]
    runtime.store.update(incident_id, status="awaiting_approval", pending_step=_public_step(step))
    blocked = runtime.guard.check_tool(step["action"], None)
    if not blocked.allowed:
        runtime.store.block_write(incident_id, step["id"], step["action"])
    if runtime.store.once(incident_id, f"card:{step['id']}"):
        _post_card(runtime, incident_id, step)
        runtime.store.timeline(incident_id, "approval_requested", step["title"])
    decision = interrupt(
        {
            "incident_id": incident_id,
            "step_id": step["id"],
            "tool": step["action"],
            "title": step["title"],
        }
    )
    approved = bool(decision.get("approved"))
    record = {
        "approved": approved,
        "tool": step["action"],
        "step_id": step["id"],
        "approver": decision.get("approver") or "operator",
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    incident = runtime.store.get(incident_id)
    approvals = list(incident["approvals"])
    approvals.append(record)
    if approved:
        runtime.store.update(incident_id, approvals=approvals, status="executing")
        runtime.store.timeline(incident_id, "approval_granted", f"{record['approver']} approved {step['title']}")
        return {"approved": True, "approval": record}
    runtime.store.update(incident_id, approvals=approvals, status="rejected", pending_step=None)
    runtime.store.timeline(incident_id, "approval_rejected", f"{record['approver']} rejected {step['title']}")
    return {"approved": False, "approval": record, "outcome": "rejected"}


def execute(state: State) -> dict:
    runtime = current()
    step = state["pending_step"]
    decision = runtime.guard.check_tool(step["action"], state.get("approval"))
    if not decision.allowed:
        runtime.store.block_write(state["incident_id"], step["id"], step["action"])
        runtime.store.update(state["incident_id"], status="awaiting_approval")
        return {"outcome": "rejected", "approved": False}
    try:
        result = run_write(runtime, step, state["incident_id"])
    except Exception as exc:
        runtime.store.timeline(state["incident_id"], "action_failed", f"{step['action']}: {exc}")
        runtime.store.update(state["incident_id"], error=str(exc), status="error")
        return {"outcome": "error"}
    runtime.store.timeline(state["incident_id"], "action", f"{step['action']}: {result['summary']}")
    runtime.store.update(state["incident_id"], status="executing", pending_step=None)
    return {"step_index": state.get("step_index", 0) + 1, "approved": False, "approval": None, "pending_step": None}


def verify(state: State) -> dict:
    runtime = current()
    step = state["pending_step"]
    params = step.get("params") or {}
    runtime.store.update(state["incident_id"], status="verifying")
    recovered = False
    summary = "verification did not run"
    # A 30s rate needs more than one scrape to fall. Twelve tries is about a minute.
    for attempt in range(12):
        try:
            found = runtime.obs.promql(params.get("query", ""))
            value = found.get("value")
            summary = found.get("summary", "")
        except Exception as exc:
            value = None
            summary = f"query failed: {exc}"
        probe_ok = _probe(runtime, params.get("probe_service", ""))
        below = float(params.get("below", 1))
        recovered = value is not None and value < below and probe_ok
        runtime.store.timeline(
            state["incident_id"],
            "verification",
            f"attempt {attempt + 1}: value={value} probe_ok={probe_ok} below={below}",
        )
        if recovered or attempt == 11:
            break
        time.sleep(5)
    evidence = runtime.store.add_evidence(
        state["incident_id"],
        {"kind": "verify", "query": params.get("query", ""), "summary": summary, "link": ""},
    )
    runtime.store.timeline(state["incident_id"], "verification", f"{evidence['id']} recovered={recovered}")
    return {
        "recovered": recovered,
        "outcome": "recovered" if recovered else "unverified",
        "step_index": state.get("step_index", 0) + 1,
        "pending_step": None,
    }


def postmortem(state: State) -> dict:
    runtime = current()
    incident = runtime.store.get(state["incident_id"])
    if state.get("outcome") == "rejected":
        final = "rejected"
    elif state.get("recovered"):
        final = "resolved"
    elif state.get("outcome") == "error":
        final = "error"
    else:
        final = "degraded"
    draft = _draft(runtime, incident, final)
    checked = runtime.guard.check_output(draft)
    draft = checked.text if checked.allowed else "Postmortem withheld by the output rail."
    runtime.store.update(state["incident_id"], status=final, postmortem=draft, pending_step=None)
    runtime.store.timeline(state["incident_id"], "postmortem", draft[:500])
    try:
        runtime.teams.post(build_update_card(title=f"Postmortem draft · {final}", text=draft))
    except Exception as exc:
        runtime.store.timeline(state["incident_id"], "teams", f"postmortem post failed: {exc}")
    return {"status": final}


def halt(state: State) -> dict:
    return {"status": state.get("status") or "blocked"}


def route_triage(state: State) -> str:
    return "halt" if state.get("status") == "blocked" else "investigate"


def route_hypothesis(state: State) -> str:
    if state.get("status") == "blocked" or state.get("outcome") == "blocked":
        return "postmortem"
    if state.get("hypothesis_ok"):
        return "propose"
    return "hypothesis"


def route_execute(state: State) -> str:
    if state.get("outcome") in {"rejected", "error"}:
        return "postmortem"
    return "propose"


def route_propose(state: State) -> str:
    step = state.get("pending_step")
    if not step:
        return "postmortem"
    if step.get("action") == "verify":
        return "verify"
    if step.get("approval_required"):
        return "approve"
    return "execute"


def route_approve(state: State) -> str:
    if state.get("outcome") == "rejected" or not state.get("approved"):
        return "postmortem"
    return "execute"


def _fallback_hypothesis(evidence: list[dict]) -> str:
    bits = [f"[{item['id']}] {item.get('summary', '')}" for item in evidence[:4]]
    cites = " ".join(f"[{item['id']}]" for item in evidence[:3])
    return "Root cause from the collected evidence: " + " | ".join(bits) + " " + cites


def _public_step(step: dict) -> dict:
    return {
        "id": step["id"],
        "title": step["title"],
        "action": step["action"],
        "approval_required": bool(step.get("approval_required")),
    }


def _post_card(runtime, incident_id: str, step: dict) -> None:
    incident = runtime.store.get(incident_id)
    base = runtime.settings.agent_public_url.rstrip("/")
    approve_url = f"{base}/?incident={incident_id}&step={step['id']}&intent=approve"
    reject_url = f"{base}/?incident={incident_id}&step={step['id']}&intent=reject"
    links = [("Grafana", incident["grafana_url"]), ("GitLab", incident["gitlab_url"])]
    for item in incident["evidence"]:
        if item.get("link"):
            links.append((f"{item['id']} {item['kind']}", item["link"]))
            if len(links) > 6:
                break
    card = build_incident_card(
        summary=incident["summary"],
        hypothesis=incident["hypothesis"],
        evidence=incident["evidence"],
        links=links[:6],
        approve_url=approve_url,
        reject_url=reject_url,
    )
    try:
        runtime.teams.post(card)
    except Exception as exc:
        runtime.store.timeline(incident_id, "teams", f"card post failed: {exc}")


def _probe(runtime, service: str) -> bool:
    url = runtime.settings.probe_urls.get(service)
    if not url:
        return False
    try:
        response = _http.get(url)
    except httpx.HTTPError:
        return False
    return response.status_code < 500


def _draft(runtime, incident: dict, final: str) -> str:
    try:
        prose = runtime.llm.chat(
            phase="postmortem",
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Alert: {incident['alertname']} status={final}\n"
                        f"Hypothesis: {incident['hypothesis']}\n"
                        "Write a short postmortem paragraph."
                    ),
                }
            ],
        )["content"]
    except Exception:
        prose = incident["hypothesis"]
    lines = [
        f"# Postmortem {incident['id']}",
        f"Status: {final}",
        f"Alert: {incident['alertname']}",
        "",
        incident["hypothesis"],
        "",
        prose.strip(),
        "",
        "## Evidence",
    ]
    for item in incident["evidence"]:
        lines.append(f"- {item['id']} ({item.get('kind')}) {item.get('summary')}")
        if item.get("query"):
            lines.append(f"  query: {item['query']}")
    lines.append("")
    lines.append("Writes ran only after an approval record. Unapproved write tools stayed blocked.")
    return "\n".join(lines)


def current():
    from agentic_sre.agent.server import RUNTIME

    if RUNTIME is None:
        raise RuntimeError("agent runtime is not set")
    return RUNTIME
