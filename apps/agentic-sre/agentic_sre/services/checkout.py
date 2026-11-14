import logging
import os

import uvicorn
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from psycopg_pool import PoolTimeout

from agentic_sre.services.common import build_app, env_flag
from agentic_sre.services.dbadmin import mount_db_admin
from agentic_sre.telemetry import current_trace_id

log = logging.getLogger("checkout")


def create_app(
    *,
    admin_token: str = "demo-admin",
    enable_telemetry: bool = False,
    loki_url: str | None = None,
    slow_s: float = 1.5,
    base_s: float = 0.01,
    database_url: str | None = None,
) -> FastAPI:
    def register(app: FastAPI) -> None:
        mount_db_admin(app, admin_token)
        app.state.metrics["db_last"].labels(service="checkout", statement="orders_by_sku").set(0)

        @app.post("/checkout")
        def checkout(body: dict | None = None):
            faults = app.state.faults
            snap = faults.snapshot()
            if snap["mode"] == "leak":
                grown = faults.grow_leak()
                app.state.metrics["memory"].labels(service="checkout").set(grown)
                log.warning("checkout leak buffer grew bytes=%s", grown)
            if snap["mode"] == "error":
                span = trace.get_current_span()
                span.set_status(Status(StatusCode.ERROR, "CheckoutFailed"))
                log.error("checkout failed error=CheckoutFailed")
                raise HTTPException(status_code=500, detail="checkout failed")
            payload = body or {}
            sku = payload.get("sku", "mug")
            qty = int(payload.get("qty", 1))
            database = app.state.db
            if database is None:
                return {"ok": True, "sku": sku, "qty": qty, "latency_s": 0}
            try:
                result = database.checkout(sku, qty, heavy=snap["mode"] == "latency")
            except PoolTimeout as exc:
                log.warning("orders-db connection pool exhausted trace_id=%s", current_trace_id())
                raise HTTPException(status_code=503, detail="orders-db pool exhausted") from exc
            except LookupError as exc:
                raise HTTPException(status_code=400, detail=f"unknown sku {exc}") from exc
            except Exception as exc:
                log.error("checkout orders-db failed error=%s trace_id=%s", exc, current_trace_id())
                raise HTTPException(status_code=503, detail="orders-db unavailable") from exc
            app.state.metrics["latency"].labels(service="checkout", dependency="orders-db").observe(result["latency_s"])
            app.state.metrics["db_last"].labels(service="checkout", statement="orders_by_sku").set(result["orders_by_sku_s"])
            if result["heavy_s"] >= slow_s or (snap["mode"] == "latency" and result["latency_s"] >= slow_s):
                log.warning(
                    "checkout dependency slow dependency=orders-db latency_s=%.3f trace_id=%s",
                    result["latency_s"],
                    current_trace_id(),
                )
            if result["orders_by_sku_s"] >= 0.08:
                log.warning(
                    "orders_by_sku sequential scan latency_s=%.3f trace_id=%s",
                    result["orders_by_sku_s"],
                    current_trace_id(),
                )
            return {
                "ok": True,
                "sku": sku,
                "qty": qty,
                "order_id": result["order_id"],
                "latency_s": result["latency_s"],
            }

    return build_app(
        "checkout",
        register,
        admin_token=admin_token,
        enable_telemetry=enable_telemetry,
        loki_url=loki_url,
        slow_s=slow_s,
        base_s=base_s,
        database_url=database_url,
        application_name="checkout",
    )


def main() -> None:
    app = create_app(
        admin_token=os.environ.get("ADMIN_TOKEN", "demo-admin"),
        enable_telemetry=env_flag("ENABLE_TELEMETRY", True),
        loki_url=os.environ.get("LOKI_URL"),
        slow_s=float(os.environ.get("FAIL_LATENCY_S", "1.5")),
        base_s=float(os.environ.get("BASE_LATENCY_S", "0.01")),
        database_url=os.environ.get("DATABASE_URL") or None,
    )
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
