import logging
import os

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from agentic_sre.services.common import build_app, env_flag
from agentic_sre.telemetry import current_trace_id

log = logging.getLogger("gateway")


def create_app(
    *,
    catalog_url: str = "http://127.0.0.1:8002",
    checkout_url: str = "http://127.0.0.1:8003",
    admin_token: str = "demo-admin",
    enable_telemetry: bool = False,
    loki_url: str | None = None,
    slow_s: float = 1.5,
    base_s: float = 0.0,
) -> FastAPI:
    client = httpx.Client(timeout=8.0, trust_env=False)

    def register(app: FastAPI) -> None:
        @app.get("/api/products")
        def products():
            _maybe_fail(app)
            try:
                response = client.get(catalog_url.rstrip("/") + "/products")
            except httpx.HTTPError as exc:
                log.error("gateway catalog unreachable error=%s", exc)
                raise HTTPException(status_code=502, detail="catalog unreachable") from exc
            if response.status_code >= 500:
                log.error(
                    "gateway upstream catalog status=%s trace_id=%s body=%s",
                    response.status_code,
                    current_trace_id(),
                    response.text[:200],
                )
                raise HTTPException(status_code=502, detail="catalog unavailable")
            return response.json()

        @app.post("/api/checkout")
        def checkout(body: dict | None = None):
            _maybe_fail(app)
            payload = body or {"sku": "mug", "qty": 1}
            try:
                stock = client.get(catalog_url.rstrip("/") + "/products")
                if stock.status_code >= 500:
                    log.error("gateway checkout blocked catalog status=%s", stock.status_code)
                    raise HTTPException(status_code=502, detail="catalog unavailable")
                response = client.post(checkout_url.rstrip("/") + "/checkout", json=payload)
            except HTTPException:
                raise
            except httpx.HTTPError as exc:
                log.error("gateway checkout unreachable error=%s", exc)
                raise HTTPException(status_code=502, detail="checkout unreachable") from exc
            if response.status_code >= 500:
                log.error("gateway upstream checkout status=%s", response.status_code)
                raise HTTPException(status_code=502, detail="checkout unavailable")
            return response.json()

    return build_app(
        "gateway",
        register,
        admin_token=admin_token,
        enable_telemetry=enable_telemetry,
        loki_url=loki_url,
        slow_s=slow_s,
        base_s=base_s,
    )


def _maybe_fail(app: FastAPI) -> None:
    faults = app.state.faults
    if faults.snapshot()["mode"] == "leak":
        grown = faults.grow_leak()
        app.state.metrics["memory"].labels(service="gateway").set(grown)
    delay = faults.delay(base_s=app.state.base_s, slow_s=app.state.slow_s)
    if delay:
        app.state.metrics["latency"].labels(service="gateway", dependency="edge").observe(delay)
    if faults.snapshot()["mode"] == "error":
        span = trace.get_current_span()
        span.set_status(Status(StatusCode.ERROR, "GatewayFail"))
        log.error("gateway fail mode error=GatewayFail")
        raise HTTPException(status_code=500, detail="gateway fail mode")


def main() -> None:
    app = create_app(
        catalog_url=os.environ.get("CATALOG_URL", "http://catalog:8000"),
        checkout_url=os.environ.get("CHECKOUT_URL", "http://checkout:8000"),
        admin_token=os.environ.get("ADMIN_TOKEN", "demo-admin"),
        enable_telemetry=env_flag("ENABLE_TELEMETRY", True),
        loki_url=os.environ.get("LOKI_URL"),
        slow_s=float(os.environ.get("FAIL_LATENCY_S", "1.5")),
    )
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
