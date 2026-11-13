import logging
import os

import uvicorn
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from agentic_sre.scenarios import BAD_DEPLOY_SHA, BAD_DEPLOY_TAG
from agentic_sre.services.common import build_app, env_flag
from agentic_sre.telemetry import current_trace_id

log = logging.getLogger("catalog")

PRODUCTS = [
    {"sku": "mug", "name": "Field mug", "price": 18},
    {"sku": "kettle", "name": "Pour kettle", "price": 42},
    {"sku": "null-row", "name": "Unpriced sample", "price": None},
]


def create_app(
    *,
    admin_token: str = "demo-admin",
    enable_telemetry: bool = False,
    loki_url: str | None = None,
    slow_s: float = 1.5,
    base_s: float = 0.0,
) -> FastAPI:
    def register(app: FastAPI) -> None:
        @app.get("/products")
        def products():
            faults = app.state.faults
            snap = faults.snapshot()
            if snap["mode"] == "leak":
                grown = faults.grow_leak()
                app.state.metrics["memory"].labels(service="catalog").set(grown)
                log.warning("catalog leak buffer grew bytes=%s", grown)
            delay = faults.delay(base_s=base_s, slow_s=slow_s)
            if delay:
                app.state.metrics["latency"].labels(service="catalog", dependency="catalog-db").observe(delay)
            if snap["mode"] == "error":
                span = trace.get_current_span()
                span.set_status(Status(StatusCode.ERROR, "NullPrice"))
                span.set_attribute("deployed.sha", BAD_DEPLOY_SHA)
                log.error(
                    "catalog product query failed error=NullPrice deployed_sha=%s tag=%s trace_id=%s",
                    BAD_DEPLOY_SHA,
                    BAD_DEPLOY_TAG,
                    current_trace_id(),
                )
                raise HTTPException(
                    status_code=500,
                    detail=f"NullPrice: product price missing after {BAD_DEPLOY_TAG}",
                )
            return {"products": PRODUCTS, "failmode": snap["mode"]}

    return build_app(
        "catalog",
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
    )
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
