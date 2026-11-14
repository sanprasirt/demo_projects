import logging
import os
import queue
import threading

import httpx

log = logging.getLogger("agentic_sre.telemetry")


def current_trace_id() -> str:
    try:
        from opentelemetry import trace

        context = trace.get_current_span().get_span_context()
        if context is not None and context.is_valid:
            return format(context.trace_id, "032x")
    except Exception:
        pass
    return "0" * 32

_ready = False
_http = httpx.Client(timeout=2.0, trust_env=False)


def setup_telemetry(service_name: str, loki_url: str | None = None) -> None:
    global _ready
    if _ready:
        return
    _ready = True
    os.environ["OTEL_SERVICE_NAME"] = service_name
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        from opentelemetry.sdk.trace import SpanProcessor

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        sanitizer = type("_BoundSanitize", (_SanitizeDbStatements, SpanProcessor), {})()
        provider.add_span_processor(sanitizer)
        if endpoint:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        if endpoint:
            _setup_logs(resource)
        from opentelemetry.instrumentation.logging import LoggingInstrumentor

        LoggingInstrumentor().instrument(set_logging_format=False)
        _instrument_psycopg()
    except Exception:
        log.exception("otel setup failed")
    if loki_url:
        root = logging.getLogger()
        root.addHandler(LokiHandler(loki_url, service_name))


class _SanitizeDbStatements:
    """Mask SQL literals on db spans before they are exported.

    Subclassed from the SDK processor once telemetry starts, so `_on_ending`
    matches the current OpenTelemetry span processor interface.
    """

    def _on_ending(self, span) -> None:
        from agentic_sre.masking import mask_sql_literals

        attrs = getattr(span, "_attributes", None)
        if not isinstance(attrs, dict):
            return
        for key in ("db.statement", "db.query.text"):
            value = attrs.get(key)
            if isinstance(value, str):
                attrs[key] = mask_sql_literals(value)
        if "db.system" not in attrs and isinstance(attrs.get("db.system.name"), str):
            attrs["db.system"] = attrs["db.system.name"]


def _instrument_psycopg() -> None:
    """DB spans carry db.system and a statement. Literals are masked on export."""
    try:
        from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor

        PsycopgInstrumentor().instrument(capture_parameters=False)
    except Exception:
        log.exception("psycopg instrumentation failed")


def _setup_logs(resource) -> None:
    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
    except Exception:
        log.exception("otlp log exporter import failed")
        return
    try:
        from opentelemetry.sdk.logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk.logs.export import BatchLogRecordProcessor
    except ImportError:
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    provider = LoggerProvider(resource=resource)
    provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(provider)
    logging.getLogger().addHandler(LoggingHandler(level=logging.INFO, logger_provider=provider))


class LokiHandler(logging.Handler):
    def __init__(self, loki_url: str, service_name: str):
        super().__init__(level=logging.WARNING)
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        self.url = loki_url.rstrip("/") + "/loki/api/v1/push"
        self.service_name = service_name
        self.queue: queue.Queue = queue.Queue(maxsize=1000)
        self.thread = threading.Thread(target=self._drain, name="loki-push", daemon=True)
        self.thread.start()

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(("httpx", "httpcore", "urllib3", "opentelemetry")):
            return
        try:
            line = self.format(record)
            self.queue.put_nowait((record.levelname.lower(), line))
        except Exception:
            return

    def _drain(self) -> None:
        while True:
            level, line = self.queue.get()
            payload = {
                "streams": [
                    {
                        "stream": {
                            "service": self.service_name,
                            "service_name": self.service_name,
                            "level": level,
                        },
                        "values": [[str(time_ns()), line]],
                    }
                ]
            }
            try:
                _http.post(self.url, json=payload)
            except Exception:
                continue


def time_ns() -> int:
    import time

    return time.time_ns()
