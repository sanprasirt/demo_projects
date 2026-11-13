"""One process that stands in for Prometheus, Loki, Tempo, and the shop admin API."""

import time

from fastapi import FastAPI, HTTPException, Request

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
        if "demo_memory_bytes" in query:
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
        if "checkout" in query:
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
