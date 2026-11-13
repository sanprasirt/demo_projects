import httpx

from agentic_sre.agent.server import create_app
from agentic_sre.scenarios import BAD_DEPLOY_SHA
from agentic_sre.services.mock_gitlab import create_app as create_gitlab
from agentic_sre.services.mock_llm import create_app as create_llm
from agentic_sre.services.mock_teams import create_app as create_teams
from agentic_sre.settings import Settings
from tests.backends import create_world
from tests.support import Running, free_port, wait_until

ALERT = {
    "status": "firing",
    "alerts": [
        {
            "status": "firing",
            "labels": {
                "alertname": "CatalogHighErrorRate",
                "service": "catalog",
                "severity": "critical",
                "scenario": "bad-deploy",
            },
            "annotations": {
                "summary": "Catalog 5xx rate is high after deploy",
                "description": "NullPrice after catalog-v1.4.2",
            },
            "startsAt": "2026-11-13T02:00:00Z",
        }
    ],
}


def _settings(world: int, llm: int, gitlab: int, teams: int) -> Settings:
    return Settings(
        llm_base_url=f"http://127.0.0.1:{llm}/v1",
        llm_model="mock-sre",
        llm_api_key="dummy",
        prometheus_url=f"http://127.0.0.1:{world}",
        loki_url=f"http://127.0.0.1:{world}",
        tempo_url=f"http://127.0.0.1:{world}",
        gitlab_url=f"http://127.0.0.1:{gitlab}",
        gitlab_public_url=f"http://127.0.0.1:{gitlab}",
        gitlab_project_id="1",
        gitlab_project_path="shop/day2-demo",
        gitlab_read_token="glpat-read-demo",
        gitlab_write_token="glpat-write-demo",
        gitlab_webhook_token="demo-webhook",
        teams_webhook_url=f"http://127.0.0.1:{teams}/webhook",
        agent_public_url="http://127.0.0.1:9",
        grafana_public_url="http://127.0.0.1:3000",
        admin_token="demo-admin",
        catalog_admin_url=f"http://127.0.0.1:{world}/services/catalog/admin/failmode",
        checkout_admin_url=f"http://127.0.0.1:{world}/services/checkout/admin/failmode",
        gateway_admin_url=f"http://127.0.0.1:{world}/services/gateway/admin/failmode",
        catalog_probe_url=f"http://127.0.0.1:{world}/services/catalog/products",
        checkout_probe_url=f"http://127.0.0.1:{world}/services/checkout/health",
        runbooks_dir="runbooks",
        nemo_dir="guardrails/nemo",
        enable_nemo=True,
    )


def test_scenario1_with_mock_llm():
    ports = {name: free_port() for name in ("world", "llm", "gitlab", "teams", "agent")}
    servers = [
        Running(create_world(), ports["world"]).start(),
        Running(create_llm(), ports["llm"]).start(),
        Running(create_gitlab(webhook_url=f"http://127.0.0.1:{ports['agent']}/api/gitlab/webhook"), ports["gitlab"]).start(),
        Running(create_teams(), ports["teams"]).start(),
    ]
    app = create_app(_settings(ports["world"], ports["llm"], ports["gitlab"], ports["teams"]))
    agent = Running(app, ports["agent"]).start()
    servers.append(agent)
    try:
        health = httpx.get(f"http://127.0.0.1:{ports['agent']}/health", timeout=5).json()
        assert health["nemo"] is True, health
        httpx.post(f"http://127.0.0.1:{ports['gitlab']}/admin/fire-webhooks", timeout=5)
        posted = httpx.post(f"http://127.0.0.1:{ports['agent']}/api/alerts", json=ALERT, timeout=5)
        assert posted.status_code == 200
        incident_id = posted.json()["incidents"][0]["id"]

        def awaiting():
            body = httpx.get(f"http://127.0.0.1:{ports['agent']}/api/incidents/{incident_id}", timeout=5).json()
            if body["status"] in {"error", "blocked"}:
                raise AssertionError(body.get("error") or body["timeline"])
            return body if body["status"] == "awaiting_approval" else None

        incident = wait_until(awaiting, timeout=60)
        assert BAD_DEPLOY_SHA in incident["hypothesis"]
        kinds = {item["kind"] for item in incident["evidence"]}
        assert {"promql", "logql", "traceql", "gitlab"} <= kinds
        assert incident["kpis"]["evidence_count"] >= 4
        assert incident["kpis"]["time_to_first_hypothesis_s"] is not None
        assert incident["kpis"]["time_to_root_cause_s"] is not None
        assert incident["kpis"]["writes_blocked"] >= 1
        assert any(event["kind"] == "gitlab_webhook" for event in incident["timeline"])
        assert any(event["kind"] == "write_blocked" for event in incident["timeline"])
        assert not any("nemo input error" in event["text"] for event in incident["timeline"])

        messages = httpx.get(f"http://127.0.0.1:{ports['teams']}/api/messages", timeout=5).json()["messages"]
        blob = str(messages)
        assert "Action.OpenUrl" in blob
        assert "Approve" in blob
        assert BAD_DEPLOY_SHA in blob

        httpx.post(
            f"http://127.0.0.1:{ports['agent']}/api/incidents/{incident_id}/decision",
            json={"approved": True, "approver": "pytest"},
            timeout=5,
        )

        def second_gate():
            body = httpx.get(f"http://127.0.0.1:{ports['agent']}/api/incidents/{incident_id}", timeout=5).json()
            if body["status"] in {"error", "rejected"}:
                raise AssertionError(body.get("error") or body["timeline"])
            step = body.get("pending_step") or {}
            return body if body["status"] == "awaiting_approval" and step.get("id") == "clear-failmode" else None

        wait_until(second_gate, timeout=30)
        mrs = httpx.get(
            f"http://127.0.0.1:{ports['gitlab']}/api/v4/projects/1/merge_requests",
            headers={"PRIVATE-TOKEN": "glpat-read-demo"},
            timeout=5,
        ).json()
        assert mrs[0]["source_branch"] == "revert-catalog-v1.4.2"

        httpx.post(
            f"http://127.0.0.1:{ports['agent']}/api/incidents/{incident_id}/decision",
            json={"approved": True, "approver": "pytest"},
            timeout=5,
        )

        def resolved():
            body = httpx.get(f"http://127.0.0.1:{ports['agent']}/api/incidents/{incident_id}", timeout=5).json()
            if body["status"] in {"error", "degraded", "rejected"}:
                raise AssertionError(body.get("error") or body["timeline"])
            return body if body["status"] == "resolved" else None

        done = wait_until(resolved, timeout=30)
        assert "Postmortem" in done["postmortem"]
        modes = httpx.get(f"http://127.0.0.1:{ports['world']}/health", timeout=5).json()["modes"]
        assert modes["catalog"] == "off"
        updated = httpx.get(f"http://127.0.0.1:{ports['teams']}/api/messages", timeout=5).json()["messages"]
        assert len(updated) >= 2
    finally:
        for server in servers:
            server.stop()
