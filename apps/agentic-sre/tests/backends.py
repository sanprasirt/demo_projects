"""One process that stands in for Prometheus, Loki, Tempo, and the shop admin API."""

import time

from fastapi import FastAPI, HTTPException, Request

from agentic_sre.agent.pg_fixture import STATE
from agentic_sre.scenarios import BAD_DEPLOY_SHA


def create_world() -> FastAPI:
    app = FastAPI()
    app.state.modes = {"catalog": "error", "checkout": "off", "gateway": "off"}

    @app.get("/health")
    def health():
        return {"ok": True, "modes": app.state.modes}

    @app.post("/services/{service}/admin/failmode")
    async def set_mode(service: str, request: Request):
        if request.headers.get("x-admin-token") != "demo-admin":
            raise HTTPException(status_code=401, detail="admin token required")
        body = await request.json()
        app.state.modes[service] = body.get("mode", "off")
        return {"mode": app.state.modes[service]}

    @app.get("/services/catalog/products")
    def products():
        if app.state.modes["catalog"] == "error":
            raise HTTPException(status_code=500, detail="NullPrice")
        return {"products": [{"sku": "mug", "price": 18}]}

    @app.get("/services/checkout/health")
    def checkout_health():
        return {"ok": True, "mode": app.state.modes["checkout"]}

    @app.get("/api/v1/query")
    def prom(query: str):
        snap = STATE.snapshot()
        if "demo_pg_activity_lock_waits" in query or "demo_pg_locks_waiting" in query:
            value = snap["lock_waits"]
        elif "demo_pg_connections_count" in query and "max_connections" in query:
            value = snap["connection_ratio"]
        elif "demo_pg_connections_count" in query:
            value = snap["connection_count"]
        elif "demo_db_last_query_seconds" in query or "orders_by_sku" in query:
            value = snap["slow_seconds"]
        elif "demo_memory_bytes" in query:
            value = 200_000_000 if app.state.modes["catalog"] == "leak" else 0
        elif "demo_dependency_latency" in query:
            value = 1.6 if app.state.modes["checkout"] == "latency" else 0.02
        elif "5.." in query or 'status=~"5' in query:
            value = 4.5 if app.state.modes["catalog"] == "error" else 0.0
        else:
            value = 0
        return {
            "status": "success",
            "data": {"resultType": "vector", "result": [{"metric": {"service": "catalog"}, "value": [0, str(value)]}]},
        }

    @app.get("/loki/api/v1/query_range")
    def loki(query: str = ""):
        if "lock" in query:
            line = "WARNING checkout orders-db lock wait blocking_pid=4242 trace_id=ccc123def4567890aaaaaaaaaaaaaaaa"
            service = "checkout"
        elif "orders_by_sku" in query or "sequential" in query:
            line = "WARNING orders_by_sku sequential scan trace_id=ddd123def4567890aaaaaaaaaaaaaaaa"
            service = "checkout"
        elif "connection" in query:
            line = "WARNING orders-db connection pool exhausted trace_id=eee123def4567890aaaaaaaaaaaaaaaa"
            service = "checkout"
        elif "checkout" in query:
            line = "WARNING checkout dependency slow dependency=orders-db latency_s=1.500 trace_id=bbb123def4567890aaaaaaaaaaaaaaaa"
            service = "checkout"
        else:
            line = (
                "ERROR catalog product query failed error=NullPrice "
                f"deployed_sha={BAD_DEPLOY_SHA} trace_id=abc123def4567890aaaaaaaaaaaaaaaa"
            )
            service = "catalog"
        return {"data": {"result": [{"stream": {"service": service}, "values": [[str(time.time_ns()), line]]}]}}

    @app.get("/api/search")
    def tempo():
        return {
            "traces": [
                {
                    "traceID": "abc123def4567890aaaaaaaaaaaaaaaa",
                    "rootTraceName": "GET /products",
                    "rootServiceName": "catalog",
                }
            ]
        }

    return app
