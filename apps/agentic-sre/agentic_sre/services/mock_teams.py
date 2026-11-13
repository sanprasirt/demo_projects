import os
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from agentic_sre.paths import UI


def create_app() -> FastAPI:
    app = FastAPI(title="mock-teams")
    app.state.messages = []

    @app.get("/health")
    def health():
        return {"ok": True, "messages": len(app.state.messages)}

    @app.post("/webhook")
    async def webhook(body: dict):
        app.state.messages.append(
            {
                "received_at": datetime.now(timezone.utc).isoformat(),
                "payload": body,
            }
        )
        return {"ok": True}

    @app.get("/api/messages")
    def messages():
        return {"messages": app.state.messages}

    @app.get("/", response_class=HTMLResponse)
    def page():
        return (UI / "teams.html").read_text(encoding="utf-8")

    return app


def main() -> None:
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8090")))
