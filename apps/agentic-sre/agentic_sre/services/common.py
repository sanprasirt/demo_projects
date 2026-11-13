import logging
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from agentic_sre.services.faults import FailState

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def make_metrics(registry: CollectorRegistry) -> dict:
    return {
        "requests": Counter(
            "demo_http_requests_total",
            "Shop HTTP responses",
            ["service", "status", "route"],
            registry=registry,
        ),
        "latency": Histogram(
            "demo_dependency_latency_seconds",
            "Injected or baseline dependency latency",
            ["service", "dependency"],
            buckets=(0.005, 0.01, 0.05, 0.1, 0.3, 0.8, 1.5, 3, 5),
            registry=registry,
        ),
        "memory": Gauge(
            "demo_memory_bytes",
            "Injected leak bytes. Zero when fail mode is off.",
            ["service"],
            registry=registry,
        ),
    }


def build_app(
    service_name: str,
    register,
    *,
    admin_token: str,
    enable_telemetry: bool,
    loki_url: str | None,
    slow_s: float,
    base_s: float,
) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    faults = FailState()
    registry = CollectorRegistry()
    metrics = make_metrics(registry)
    metrics["memory"].labels(service=service_name).set(0)
    app = FastAPI(title=service_name)
    app.state.faults = faults
    app.state.metrics = metrics
    app.state.service_name = service_name
    app.state.slow_s = slow_s
    app.state.base_s = base_s

    @app.get("/health")
    def health():
        return {"ok": True, "service": service_name, "failmode": faults.snapshot()}

    @app.get("/admin/failmode")
    def get_mode():
        return faults.snapshot()

    @app.post("/admin/failmode")
    async def set_mode(request: Request):
        if request.headers.get("x-admin-token") != admin_token:
            raise HTTPException(status_code=401, detail="admin token required")
        body = await request.json()
        mode = body.get("mode", "off")
        try:
            faults.set(mode, body.get("note", ""))
        except ValueError:
            raise HTTPException(status_code=400, detail="mode must be off, error, leak, or latency") from None
        metrics["memory"].labels(service=service_name).set(faults.snapshot()["leak_bytes"])
        return faults.snapshot()

    @app.get("/metrics")
    def metrics_route():
        metrics["memory"].labels(service=service_name).set(faults.snapshot()["leak_bytes"])
        return Response(generate_latest(registry), media_type=CONTENT_TYPE)

    register(app)

    @app.middleware("http")
    async def count_requests(request: Request, call_next):
        if request.url.path in {"/metrics", "/health"}:
            return await call_next(request)
        response = await call_next(request)
        metrics["requests"].labels(service_name, str(response.status_code), request.url.path).inc()
        return response

    if enable_telemetry:
        from agentic_sre.telemetry import setup_telemetry

        setup_telemetry(service_name, loki_url=loki_url)
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()
    return app


def env_flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw not in {"0", "false", "False"}
