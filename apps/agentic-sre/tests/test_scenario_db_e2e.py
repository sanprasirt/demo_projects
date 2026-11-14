import httpx

from agentic_sre.agent.pg_fixture import STATE
from agentic_sre.agent.server import create_app
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
                "alertname": "DBLockWaitsHigh",
                "service": "postgres",
                "severity": "warning",
                "scenario": "lock-contention",
            },
            "annotations": {
                "summary": "Postgres sessions are waiting on locks",
                "description": "pg_stat_activity shows a lock wait and a blocking pid",
            },
            "startsAt": "2026-11-14T02:10:00Z",
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
        pg_read_dsn="fixture://lock",
        pg_write_dsn="fixture://lock",
    )


def test_lock_scenario_with_mock_llm():
    STATE.arm_lock()
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
        posted = httpx.post(f"http://127.0.0.1:{ports['agent']}/api/alerts", json=ALERT, timeout=5)
        assert posted.status_code == 200
        incident_id = posted.json()["incidents"][0]["id"]

        def awaiting():
            body = httpx.get(f"http://127.0.0.1:{ports['agent']}/api/incidents/{incident_id}", timeout=5).json()
            if body["status"] in {"error", "blocked"}:
                raise AssertionError(body.get("error") or body["timeline"])
            return body if body["status"] == "awaiting_approval" else None

        incident = wait_until(awaiting, timeout=60)
        assert incident["pending_step"]["action"] == "pg_terminate_backend"
        assert incident["kpis"]["writes_blocked"] >= 1
        blob = str(incident["evidence"])
        assert "'mug'" not in blob
        assert "'locked-sku'" not in blob
        kinds = {item["kind"] for item in incident["evidence"]}
        assert "pg_activity" in kinds
        assert "pg_statements" in kinds
        activity = next(item for item in incident["evidence"] if item["kind"] == "pg_activity")
        assert "4242" in activity["summary"]
        assert "lock" in incident["hypothesis"].lower() or "blocking" in incident["hypothesis"].lower()
        assert any(event["kind"] == "write_blocked" for event in incident["timeline"])

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
        assert STATE.snapshot()["lock_waits"] == 0
    finally:
        STATE.clear_lock("test")
        for server in servers:
            server.stop()
