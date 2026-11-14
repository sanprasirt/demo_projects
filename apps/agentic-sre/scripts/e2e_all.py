"""Run every Day-2 scenario against a stack that is already up.

The stack is docker compose with the mock profile: mock LLM, mock Teams, and
mock GitLab. This script injects each fault, waits for Prometheus and
Alertmanager to page the agent, checks the evidence and the Adaptive Card,
approves the runbook writes, and waits until the incident and the alert recover.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROM = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
AGENT = os.environ.get("AGENT_URL", "http://localhost:8080")
TEAMS = os.environ.get("TEAMS_URL", "http://localhost:8090")
CATALOG = os.environ.get("CATALOG_URL", "http://localhost:8002")
CHECKOUT = os.environ.get("CHECKOUT_URL", "http://localhost:8003")

SCENARIOS = [
    {
        "n": "1",
        "name": "bad-deploy",
        "inject": "scripts/scenario1_inject.sh",
        "reset": "scripts/scenario1_reset.sh",
        "alert": "CatalogHighErrorRate",
        "runbook": "bad-deploy",
        "kinds": ["promql", "logql", "traceql", "gitlab", "runbook"],
        "needles": ["NullPrice", "badc0ffee"],
        "actions": ["gitlab_open_revert_mr", "set_failmode"],
        "metric": 'sum(rate(demo_http_requests_total{service="catalog",status=~"5.."}[1m]))',
        "below": 0.5,
    },
    {
        "n": "2",
        "name": "memory-leak",
        "inject": "scripts/scenario2_inject.sh",
        "reset": "scripts/scenario2_reset.sh",
        "alert": "ServiceMemoryHigh",
        "runbook": "memory-leak",
        "kinds": ["promql", "logql", "traceql", "gitlab", "runbook"],
        "needles": ["leak"],
        "actions": ["set_failmode"],
        "metric": 'max(demo_memory_bytes{service="catalog"})',
        "below": 50_000_000,
    },
    {
        "n": "3",
        "name": "dependency-latency",
        "inject": "scripts/scenario3_inject.sh",
        "reset": "scripts/scenario3_reset.sh",
        "alert": "DependencyLatencyHigh",
        "runbook": "dependency-latency",
        "kinds": ["promql", "logql", "traceql", "gitlab", "runbook"],
        "needles": ["latency", "orders-db"],
        "actions": ["set_failmode"],
        "metric": (
            'sum(rate(demo_dependency_latency_seconds_sum{service="checkout",dependency="orders-db"}[1m]))'
            ' / sum(rate(demo_dependency_latency_seconds_count{service="checkout",dependency="orders-db"}[1m]))'
        ),
        "below": 0.8,
    },
    {
        "n": "4",
        "name": "lock-contention",
        "inject": "scripts/scenario4_inject.sh",
        "reset": "scripts/scenario4_reset.sh",
        "alert": "DBLockWaitsHigh",
        "runbook": "lock-contention",
        "kinds": ["promql", "pg_activity", "pg_statements", "logql", "traceql", "runbook"],
        "needles": ["lock", "blocking"],
        "actions": ["pg_terminate_backend"],
        "metric": "sum(demo_pg_activity_lock_waits)",
        "below": 1,
    },
    {
        "n": "5",
        "name": "connection-saturation",
        "inject": "scripts/scenario5_inject.sh",
        "reset": "scripts/scenario5_reset.sh",
        "alert": "DBConnectionsSaturated",
        "runbook": "connection-saturation",
        "kinds": ["promql", "pg_activity", "pg_statements", "logql", "traceql", "runbook"],
        "needles": ["connection", "sre-hold"],
        "actions": ["pg_terminate_backend"],
        "metric": "sum(demo_pg_connections_count) / max(demo_pg_settings_max_connections)",
        "below": 0.75,
    },
    {
        "n": "6",
        "name": "missing-index",
        "inject": "scripts/scenario6_inject.sh",
        "reset": "scripts/scenario6_reset.sh",
        "alert": "DBSlowQueries",
        "runbook": "slow-query",
        "kinds": ["promql", "pg_statements", "pg_activity", "logql", "traceql", "runbook"],
        "needles": ["orders_by_sku"],
        "actions": ["pg_create_index"],
        "metric": 'max(demo_db_last_query_seconds{statement="orders_by_sku"})',
        "below": 0.08,
    },
]


def get(url: str):
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.load(response)


def post(url: str, payload: dict):
    body = json.dumps(payload).encode()
    request = urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def prom_query(query: str):
    url = PROM + "/api/v1/query?" + urllib.parse.urlencode({"query": query})
    body = get(url)
    result = body.get("data", {}).get("result") or []
    if not result:
        return None
    try:
        return float(result[0]["value"][1])
    except (KeyError, TypeError, ValueError):
        return None


def alert_state(name: str) -> str:
    body = get(PROM + "/api/v1/rules")
    for group in body["data"]["groups"]:
        for rule in group["rules"]:
            if rule.get("name") == name:
                return rule.get("state") or "unknown"
    return "missing"


def incidents() -> list[dict]:
    return get(AGENT + "/api/incidents")["incidents"]


def incident(incident_id: str) -> dict:
    return get(AGENT + f"/api/incidents/{incident_id}")


def teams_messages() -> list[dict]:
    return get(TEAMS + "/api/messages")["messages"]


def run_script(path: str) -> None:
    subprocess.run(["sh", str(ROOT / path)], cwd=ROOT, check=True)


def wait_until(predicate, timeout: float, label: str):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(2)
    raise TimeoutError(f"timed out waiting for {label}: {last}")


def quiet_alerts(names: list[str], timeout: float = 90) -> None:
    def clear():
        states = {name: alert_state(name) for name in names}
        return states if all(state != "firing" for state in states.values()) else None

    wait_until(clear, timeout, "alerts to stop firing")


def evidence_blob(inc: dict) -> str:
    return json.dumps(inc.get("evidence") or [])


def check_evidence(inc: dict, spec: dict) -> tuple[bool, str]:
    kinds = {item.get("kind") for item in inc.get("evidence") or []}
    missing = [kind for kind in spec["kinds"] if kind not in kinds]
    blob = evidence_blob(inc).lower()
    absent = [needle for needle in spec["needles"] if needle.lower() not in blob]
    weak = []
    for item in inc.get("evidence") or []:
        summary = (item.get("summary") or "").lower()
        if item.get("kind") in spec["kinds"] and (
            summary.startswith("tool failed") or summary in {"no log lines", "no traces", "no series"}
        ):
            weak.append(f"{item.get('id')}:{item.get('kind')}:{summary}")
    ok = not missing and not absent and not weak
    detail = []
    if missing:
        detail.append("missing " + ",".join(missing))
    if absent:
        detail.append("text " + ",".join(absent))
    if weak:
        detail.append("weak " + "; ".join(weak))
    found = ",".join(sorted(kinds))
    return ok, found + (("; " + "; ".join(detail)) if detail else "")


def card_ok(spec: dict, incident_id: str, before: int) -> bool:
    messages = teams_messages()[before:]
    blob = json.dumps(messages)
    return "Action.OpenUrl" in blob and "Approve" in blob and incident_id in blob


def approve_all(incident_id: str, actions: list[str]) -> list[str]:
    approved: list[str] = []
    deadline = time.time() + 180
    while time.time() < deadline and approved != actions:
        current = incident(incident_id)
        status = current["status"]
        if status in {"resolved", "degraded", "error", "rejected", "blocked"}:
            break
        step = current.get("pending_step") or {}
        if status == "awaiting_approval" and step.get("action"):
            step_id = step.get("id")
            post(
                AGENT + f"/api/incidents/{incident_id}/decision",
                {"approved": True, "approver": "e2e"},
            )
            approved.append(step["action"])

            def moved(expected=step_id):
                body = incident(incident_id)
                pending = (body.get("pending_step") or {}).get("id")
                if body["status"] != "awaiting_approval" or pending != expected:
                    return body
                return None

            try:
                wait_until(moved, 40, f"step {step_id} to finish")
            except TimeoutError:
                break
            continue
        time.sleep(1)
    return approved


def metric_recovered(spec: dict) -> bool:
    if alert_state(spec["alert"]) == "firing":
        return False
    value = prom_query(spec["metric"])
    if value is None:
        return True
    return value < spec["below"]


def run_scenario(spec: dict) -> dict:
    print(f"\n=== scenario {spec['n']} {spec['name']} ===", flush=True)
    row = {
        "scenario": f"{spec['n']} {spec['name']}",
        "alert": spec["alert"],
        "runbook": "",
        "evidence": "",
        "approval": "",
        "recovered": "no",
        "diagnosis_s": "",
        "pass": False,
        "note": "",
    }
    try:
        for other in SCENARIOS:
            run_script(other["reset"])
        quiet_alerts([item["alert"] for item in SCENARIOS], timeout=120)
        before_messages = len(teams_messages())
        known = {item["id"] for item in incidents()}
        started = time.time()
        run_script(spec["inject"])

        def firing():
            return alert_state(spec["alert"]) == "firing" or None

        wait_until(firing, 120, spec["alert"])

        def waiting():
            for item in incidents():
                if item["id"] in known or item.get("alertname") != spec["alert"]:
                    continue
                if item["status"] == "awaiting_approval" and item.get("runbook_id") == spec["runbook"]:
                    return item
                if item["status"] in {"error", "blocked", "degraded", "rejected"}:
                    raise RuntimeError(f"incident {item['id']} is {item['status']}: {item.get('error')}")
            return None

        inc = wait_until(waiting, 120, "agent awaiting approval")
        diagnosis = round(time.time() - started, 1)
        row["diagnosis_s"] = str(diagnosis)
        row["runbook"] = inc.get("runbook_id") or ""
        ok_evidence, evidence_text = check_evidence(inc, spec)
        row["evidence"] = evidence_text
        if not card_ok(spec, inc["id"], before_messages):
            raise RuntimeError("Teams card missing Approve link")
        approved = approve_all(inc["id"], spec["actions"])
        row["approval"] = ",".join(approved) or "none"

        def done():
            body = incident(inc["id"])
            if body["status"] in {"resolved", "degraded", "error", "rejected"}:
                return body
            return None

        final = wait_until(done, 180, "incident to finish")
        if final["status"] != "resolved":
            raise RuntimeError(f"status {final['status']}")
        if approved != spec["actions"]:
            raise RuntimeError(f"approved {approved}, expected {spec['actions']}")
        wait_until(lambda: metric_recovered(spec) or None, 120, "alert and metric to recover")
        if not ok_evidence:
            raise RuntimeError("evidence check failed: " + evidence_text)
        row["recovered"] = "yes"
        row["pass"] = True
        kpi = final.get("kpis") or {}
        row["note"] = f"kpi_root_cause={kpi.get('time_to_root_cause_s')}s evidence={kpi.get('evidence_count')}"
        print(f"PASS {spec['name']} diagnosis={diagnosis}s {row['note']}", flush=True)
    except Exception as exc:
        row["note"] = str(exc)
        row["pass"] = False
        print(f"FAIL {spec['name']}: {exc}", flush=True)
    finally:
        try:
            run_script(spec["reset"])
        except subprocess.CalledProcessError as exc:
            row["note"] = (row["note"] + f"; reset failed: {exc}").strip("; ")
            row["pass"] = False
            row["recovered"] = "no"
    return row


def preflight() -> None:
    health = get(AGENT + "/health")
    if not health.get("ok") or not health.get("nemo"):
        raise SystemExit(f"agent is not ready: {health}")
    products = urllib.request.urlopen(CATALOG + "/products", timeout=10)
    if products.status >= 400:
        raise SystemExit(f"catalog /products returned {products.status}")
    state = alert_state("CatalogHighErrorRate")
    if state == "missing":
        raise SystemExit("Prometheus did not load the Day-2 alert rules")
    print(f"preflight ok model={health.get('model')} nemo={health.get('nemo')}", flush=True)


def print_table(rows: list[dict]) -> None:
    headers = ["scenario", "alert", "runbook", "evidence", "approval", "recovered", "diagnosis_s", "pass"]
    print("\n| " + " | ".join(headers) + " |")
    print("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        cells = []
        for key in headers:
            value = "pass" if key == "pass" and row["pass"] else "fail" if key == "pass" else str(row.get(key, ""))
            cells.append(value.replace("|", "/").replace("\n", " "))
        print("| " + " | ".join(cells) + " |")
        if row.get("note"):
            print(f"  note: {row['note']}")


def main() -> int:
    os.chdir(ROOT)
    selected = {item for item in sys.argv[1:] if item}
    specs = [item for item in SCENARIOS if not selected or item["n"] in selected or item["name"] in selected]
    if not specs:
        raise SystemExit(f"no scenarios matched {sys.argv[1:]}")
    preflight()
    rows = [run_scenario(spec) for spec in specs]
    print_table(rows)
    out = Path("/tmp/e2e-results.json")
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0 if all(row["pass"] for row in rows) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as exc:
        raise SystemExit(f"stack is not reachable: {exc}") from exc
