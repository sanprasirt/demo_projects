from fastapi.testclient import TestClient

from agentic_sre.services.catalog import create_app


def test_failmode_is_reversible_and_requires_a_token():
    app = create_app(admin_token="demo-admin", enable_telemetry=False, slow_s=0.0, base_s=0.0)
    client = TestClient(app)
    assert client.get("/products").status_code == 200
    denied = client.post("/admin/failmode", json={"mode": "error"})
    assert denied.status_code == 401
    headers = {"x-admin-token": "demo-admin"}
    turned_on = client.post("/admin/failmode", headers=headers, json={"mode": "error", "note": "scenario-1"})
    assert turned_on.status_code == 200
    failed = client.get("/products")
    assert failed.status_code == 500
    assert "NullPrice" in failed.text
    leaked = client.post("/admin/failmode", headers=headers, json={"mode": "leak"})
    assert leaked.status_code == 200
    client.get("/products")
    snap = client.get("/admin/failmode").json()
    assert snap["mode"] == "leak"
    assert snap["leak_bytes"] > 0
    reset = client.post("/admin/failmode", headers=headers, json={"mode": "off"})
    assert reset.json()["leak_bytes"] == 0
    assert client.get("/products").status_code == 200
