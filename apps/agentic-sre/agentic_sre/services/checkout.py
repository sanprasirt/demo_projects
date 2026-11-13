import logging
import os

import uvicorn
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from agentic_sre.services.common import build_app, env_flag
from agentic_sre.telemetry import current_trace_id

log = logging.getLogger("checkout")


def create_app(
    *,
    admin_token: str = "demo-admin",
    enable_telemetry: bool = False,
    loki_url: str | None = None,
    slow_s: float = 1.5,
    base_s: float = 0.01,
) -> FastAPI:
    def register(app: FastAPI) -> None:
        @app.post("/checkout")
        async def checkout(body: dict | None = None):
            faults = app.state.faults
            if faults.snapshot()["mode"] == "leak":
                grown = faults.grow_leak()
                app.state.metrics["memory"].labels(service="checkout").set(grown)
                log.warning("checkout leak buffer grew bytes=%s", grown)
            delay = faults.delay(base_s=app.state.base_s, slow_s=app.state.slow_s)
            app.state.metrics["latency"].labels(service="checkout", dependency="orders-db").observe(delay)
            if delay >= slow_s and faults.snapshot()["mode"] == "latency":
                log.warning(
                    "checkout dependency slow dependency=orders-db latency_s=%.3f trace_id=%s",
                    delay,
                    current_trace_id(),
                )
            if faults.snapshot()["mode"] == "error":
                span = trace.get_current_span()
                span.set_status(Status(StatusCode.ERROR, "CheckoutFailed"))
                log.error("checkout failed error=CheckoutFailed")
                raise HTTPException(status_code=500, detail="checkout failed")
            payload = body or {}
            return {"ok": True, "sku": payload.get("sku", "mug"), "qty": payload.get("qty", 1), "latency_s": delay}

    return build_app(
        "checkout",
        register,
        admin_token=admin_token,
        enable_telemetry=enable_telemetry,
        loki_url=loki_url,
        slow_s=slow_s,
        base_s=base_s,
    )


def main() -> None:
    app = create_app(
        admin_token=os.environ.get("ADMIN_TOKEN", "demo-admin"),
        enable_telemetry=env_flag("ENABLE_TELEMETRY", True),
        loki_url=os.environ.get("LOKI_URL"),
        slow_s=float(os.environ.get("FAIL_LATENCY_S", "1.5")),
        base_s=float(os.environ.get("BASE_LATENCY_S", "0.01")),
    )
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
