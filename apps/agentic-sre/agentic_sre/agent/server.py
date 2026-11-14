import logging
import threading

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langgraph.types import Command

from agentic_sre.agent.gitlab_client import GitLabClient
from agentic_sre.agent.graph import build_graph
from agentic_sre.agent.guardrails import Guardrails
from agentic_sre.agent.llm import LLM
from agentic_sre.agent.obs import ObsClient
from agentic_sre.agent.pg import PgClient
from agentic_sre.agent.runbooks import RunbookLibrary
from agentic_sre.agent.store import IncidentStore
from agentic_sre.agent.teams import TeamsClient
from agentic_sre.paths import UI
from agentic_sre.settings import Settings

log = logging.getLogger("agentic_sre.server")
RUNTIME = None


class Runtime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = IncidentStore()
        self.lock = threading.Lock()
        self.llm = LLM(settings.llm_base_url, settings.llm_model, settings.llm_api_key)
        self.obs = ObsClient(settings.prometheus_url, settings.loki_url, settings.tempo_url, settings.grafana_public_url)
        self.gitlab = GitLabClient(
            settings.gitlab_url,
            settings.gitlab_read_token,
            settings.gitlab_write_token,
            settings.gitlab_project_id,
            public_url=settings.gitlab_public_url,
            project_path=settings.gitlab_project_path,
        )
        self.teams = TeamsClient(settings.teams_webhook_url)
        self.pg = PgClient(settings.pg_read_dsn, settings.pg_write_dsn, settings.grafana_public_url)
        self.runbooks = RunbookLibrary(settings.runbooks_dir)
        self.guard = Guardrails(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            nemo_dir=settings.nemo_dir,
            enable_nemo=settings.enable_nemo,
        )
        self.graph = build_graph()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    runtime = Runtime(settings)
    app = FastAPI(title="Day-2 SRE agent")
    app.state.runtime = runtime

    @app.get("/health")
    def health():
        return {
            "ok": True,
            "nemo": runtime.guard.rails is not None,
            "nemo_error": runtime.guard.nemo_error,
            "model": settings.llm_model,
        }

    @app.get("/api/meta")
    def meta():
        return {
            "model": settings.llm_model,
            "llm_base_url": settings.llm_base_url,
            "read_only_default": True,
            "nemo": runtime.guard.rails is not None,
            "grafana_url": settings.grafana_public_url,
            "gitlab_url": settings.gitlab_public_url,
        }

    @app.get("/api/incidents")
    def list_incidents():
        return {"incidents": runtime.store.list()}

    @app.get("/api/incidents/{incident_id}")
    def get_incident(incident_id: str):
        found = runtime.store.get(incident_id)
        if found is None:
            raise HTTPException(status_code=404, detail="incident not found")
        return found

    @app.post("/api/alerts")
    async def alerts(request: Request):
        body = await request.json()
        return {"incidents": ingest_alerts(runtime, body)}

    @app.post("/api/gitlab/webhook")
    async def gitlab_hook(request: Request):
        token = request.headers.get("x-gitlab-token", "")
        if settings.gitlab_webhook_token and token != settings.gitlab_webhook_token:
            raise HTTPException(status_code=401, detail="webhook token rejected")
        body = await request.json()
        event = request.headers.get("x-gitlab-event", "gitlab")
        runtime.store.note_gitlab(event, body)
        return {"ok": True}

    @app.post("/api/incidents/{incident_id}/decision")
    async def decision(incident_id: str, request: Request):
        if runtime.store.get(incident_id) is None:
            raise HTTPException(status_code=404, detail="incident not found")
        body = await request.json()
        threading.Thread(
            target=resume,
            args=(runtime, incident_id, bool(body.get("approved")), body.get("approver") or "operator"),
            daemon=True,
        ).start()
        return {"ok": True}

    @app.get("/")
    def index():
        return FileResponse(UI / "index.html")

    app.mount("/static", StaticFiles(directory=UI), name="static")
    return app


def ingest_alerts(runtime: Runtime, payload: dict) -> list[dict]:
    created = []
    for alert in payload.get("alerts") or []:
        labels = alert.get("labels") or {}
        if alert.get("status") != "firing":
            runtime.store.note_resolved(labels.get("alertname", ""), "alertmanager resolved")
            continue
        fingerprint = f"{labels.get('alertname', '')}|{alert.get('startsAt', '')}"
        if runtime.store.by_fingerprint(fingerprint):
            continue
        incident = runtime.store.create(
            alert,
            grafana_url=runtime.settings.grafana_public_url.rstrip("/") + "/d/day2/day-2-operations",
            gitlab_url=runtime.settings.gitlab_public_url.rstrip("/") + "/" + runtime.settings.gitlab_project_path,
        )
        created.append({"id": incident["id"]})
        threading.Thread(target=start, args=(runtime, incident["id"]), daemon=True).start()
    return created


def start(runtime: Runtime, incident_id: str) -> None:
    incident = runtime.store.get(incident_id)
    initial = {
        "incident_id": incident_id,
        "alertname": incident["alertname"],
        "alert_text": (
            f"{incident['summary']}\n{incident['description']}\n"
            f"scenario={incident['scenario']} service={incident['service']}"
        ),
        "status": "investigating",
        "hypothesis_attempts": 0,
        "step_index": 0,
        "hypothesis_ok": False,
        "recovered": False,
    }
    _invoke(runtime, incident_id, initial, None)


def resume(runtime: Runtime, incident_id: str, approved: bool, approver: str) -> None:
    _invoke(runtime, incident_id, None, {"approved": approved, "approver": approver})


def _invoke(runtime: Runtime, incident_id: str, initial: dict | None, resume_value: dict | None) -> None:
    global RUNTIME
    with runtime.lock:
        RUNTIME = runtime
        try:
            config = {"configurable": {"thread_id": incident_id}}
            if resume_value is None:
                runtime.graph.invoke(initial, config)
            else:
                runtime.graph.invoke(Command(resume=resume_value), config)
        except _interrupt_type() as exc:
            log.info("graph paused: %s", exc)
        except Exception as exc:
            log.exception("graph failed")
            runtime.store.update(incident_id, status="error", error=str(exc))
            runtime.store.timeline(incident_id, "error", str(exc))


class _NoInterrupt(Exception):
    pass


def _interrupt_type():
    try:
        from langgraph.errors import GraphInterrupt

        return GraphInterrupt
    except Exception:
        return _NoInterrupt


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    import os

    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
