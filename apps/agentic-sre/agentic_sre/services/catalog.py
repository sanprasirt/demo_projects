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
    database_url: str | None = None,
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
            database = app.state.db
            if database is None:
                if snap["mode"] == "error":
                    _null_price()
                return {"products": PRODUCTS, "failmode": snap["mode"]}
            try:
                rows, elapsed = database.list_products(include_unpriced=snap["mode"] == "error")
            except Exception as exc:
                log.error("catalog product query failed error=%s trace_id=%s", exc, current_trace_id())
                raise HTTPException(status_code=503, detail="catalog-db unavailable") from exc
            app.state.metrics["latency"].labels(service="catalog", dependency="catalog-db").observe(elapsed)
            app.state.metrics["db_last"].labels(service="catalog", statement="products").set(elapsed)
            if snap["mode"] == "error" and any(row["price"] is None for row in rows):
                _null_price()
            return {"products": rows, "failmode": snap["mode"]}

    return build_app(
        "catalog",
        register,
        admin_token=admin_token,
        enable_telemetry=enable_telemetry,
        loki_url=loki_url,
        slow_s=slow_s,
        base_s=base_s,
        database_url=database_url,
        application_name="catalog",
    )


def _null_price() -> None:
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


def main() -> None:
    app = create_app(
        admin_token=os.environ.get("ADMIN_TOKEN", "demo-admin"),
        enable_telemetry=env_flag("ENABLE_TELEMETRY", True),
        loki_url=os.environ.get("LOKI_URL"),
        slow_s=float(os.environ.get("FAIL_LATENCY_S", "1.5")),
        database_url=os.environ.get("DATABASE_URL") or None,
    )
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
