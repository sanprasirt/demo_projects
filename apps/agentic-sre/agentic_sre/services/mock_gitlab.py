"""GitLab-shaped API with the bad-deploy seed already loaded."""

import os
import threading
from datetime import datetime, timezone

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from agentic_sre.gitlab_seed import BAD_FILE, PREVIOUS_FILE, commits, deployments, pipelines, project, tags
from agentic_sre.scenarios import BAD_DEPLOY_SHA, BAD_DEPLOY_TAG, PROJECT_PATH

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def create_app(
    *,
    read_token: str = "glpat-read-demo",
    write_token: str = "glpat-write-demo",
    public_base: str = "http://localhost:8929",
    webhook_url: str = "",
    webhook_token: str = "demo-webhook",
) -> FastAPI:
    app = FastAPI(title="mock-gitlab")
    state = {
        "project": project(public_base),
        "commits": commits(public_base, _now()),
        "pipelines": pipelines(public_base, _now()),
        "deployments": deployments(public_base, _now()),
        "tags": tags(),
        "merge_requests": [],
        "hooks": [],
        "next_iid": 1,
        "next_pipeline": 100,
    }
    app.state.box = state
    app.state.read_token = read_token
    app.state.write_token = write_token
    app.state.public_base = public_base.rstrip("/")
    app.state.webhook_url = webhook_url
    app.state.webhook_token = webhook_token
    client = httpx.Client(timeout=5.0, trust_env=False)

    def require(request: Request, write: bool = False) -> None:
        token = request.headers.get("private-token", "")
        allowed = {write_token} if write else {read_token, write_token}
        if token not in allowed:
            raise HTTPException(status_code=403 if token else 401, detail="token rejected")

    @app.get("/health")
    def health():
        return {"ok": True, "service": "mock-gitlab"}

    @app.get("/api/v4/user")
    def user(request: Request):
        require(request)
        token = request.headers.get("private-token")
        return {"id": 1, "username": "root", "token_kind": "write" if token == write_token else "read"}

    @app.get("/api/v4/projects/{project_id}")
    def get_project(project_id: int, request: Request):
        require(request)
        if project_id != state["project"]["id"]:
            raise HTTPException(status_code=404, detail="project not found")
        return state["project"]

    @app.post("/api/v4/projects")
    async def create_project(request: Request):
        require(request, write=True)
        return state["project"]

    @app.get("/api/v4/projects/{project_id}/repository/commits")
    def list_commits(project_id: int, request: Request):
        require(request)
        return state["commits"]

    @app.post("/api/v4/projects/{project_id}/repository/commits")
    async def create_commit(project_id: int, request: Request):
        require(request, write=True)
        return state["commits"][0]

    @app.get("/api/v4/projects/{project_id}/repository/tags")
    def list_tags(project_id: int, request: Request):
        require(request)
        return state["tags"]

    @app.post("/api/v4/projects/{project_id}/repository/tags")
    async def create_tag(project_id: int, request: Request):
        require(request, write=True)
        return state["tags"][0]

    @app.get("/api/v4/projects/{project_id}/pipelines")
    def list_pipelines(project_id: int, request: Request):
        require(request)
        return state["pipelines"]

    @app.get("/api/v4/projects/{project_id}/deployments")
    def list_deployments(project_id: int, request: Request):
        require(request)
        return state["deployments"]

    @app.post("/api/v4/projects/{project_id}/deployments")
    async def create_deployment(project_id: int, request: Request):
        require(request, write=True)
        body = await request.json()
        created = _now()
        item = deployments(app.state.public_base, created)[0]
        item["sha"] = body.get("sha", item["sha"])
        item["ref"] = body.get("ref", item["ref"])
        item["status"] = body.get("status", "success")
        item["created_at"] = created
        state["deployments"].insert(0, item)
        return item

    @app.get("/api/v4/projects/{project_id}/merge_requests")
    def list_mrs(project_id: int, request: Request):
        require(request)
        return state["merge_requests"]

    @app.post("/api/v4/projects/{project_id}/merge_requests")
    async def open_mr(project_id: int, request: Request):
        require(request, write=True)
        body = await request.json()
        with _lock:
            iid = state["next_iid"]
            state["next_iid"] += 1
        web = f"{app.state.public_base}/{PROJECT_PATH}/-/merge_requests/{iid}"
        mr = {
            "iid": iid,
            "id": iid,
            "title": body.get("title", "revert"),
            "description": body.get("description", ""),
            "state": "opened",
            "source_branch": body.get("source_branch", "revert"),
            "target_branch": body.get("target_branch", "main"),
            "sha": BAD_DEPLOY_SHA,
            "web_url": web,
            "created_at": _now(),
        }
        state["merge_requests"].insert(0, mr)
        return mr

    @app.get("/api/v4/projects/{project_id}/hooks")
    def list_hooks(project_id: int, request: Request):
        require(request)
        return state["hooks"]

    @app.post("/api/v4/projects/{project_id}/hooks")
    async def add_hook(project_id: int, request: Request):
        require(request, write=True)
        body = await request.json()
        hook = {"id": len(state["hooks"]) + 1, "url": body.get("url"), "deployment_events": True}
        state["hooks"].append(hook)
        return hook

    @app.post("/admin/fire-webhooks")
    def fire(body: dict | None = None):
        created = _now()
        state["deployments"] = deployments(app.state.public_base, created)
        state["pipelines"] = pipelines(app.state.public_base, created)
        state["commits"] = commits(app.state.public_base, created)
        targets = [hook["url"] for hook in state["hooks"] if hook.get("url")]
        if app.state.webhook_url:
            targets.append(app.state.webhook_url)
        sent = []
        deployment_payload = {
            "object_kind": "deployment",
            "status": "success",
            "status_changed_at": created,
            "deployable_id": 100,
            "short_sha": BAD_DEPLOY_SHA[:12],
            "sha": BAD_DEPLOY_SHA,
            "ref": BAD_DEPLOY_TAG,
            "environment": "production",
            "project": {"id": 1, "name": "day2-demo", "path_with_namespace": PROJECT_PATH},
        }
        pipeline_payload = {
            "object_kind": "pipeline",
            "object_attributes": {
                "id": state["pipelines"][0]["id"],
                "ref": BAD_DEPLOY_TAG,
                "sha": BAD_DEPLOY_SHA,
                "status": "success",
            },
            "project": {"id": 1, "path_with_namespace": PROJECT_PATH},
        }
        for url in targets:
            for event, payload in (("Deployment Hook", deployment_payload), ("Pipeline Hook", pipeline_payload)):
                try:
                    client.post(url, json=payload, headers={"X-Gitlab-Event": event, "X-Gitlab-Token": app.state.webhook_token})
                    sent.append({"url": url, "event": event})
                except httpx.HTTPError as exc:
                    sent.append({"url": url, "event": event, "error": str(exc)})
        return {"ok": True, "sent": sent, "sha": BAD_DEPLOY_SHA}

    @app.get(f"/{PROJECT_PATH}", response_class=HTMLResponse)
    @app.get(f"/{PROJECT_PATH}/-/commit/{BAD_DEPLOY_SHA}", response_class=HTMLResponse)
    def commit_page():
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{BAD_DEPLOY_TAG}</title>
<style>
body {{ margin: 0; font-family: ui-sans-serif, system-ui, sans-serif; background: #1f1e24; color: #ece8f4; }}
main {{ max-width: 860px; margin: 0 auto; padding: 32px 20px; }}
.sha {{ font-family: ui-monospace, monospace; color: #f0c36a; }}
pre {{ background: #141318; padding: 16px; overflow: auto; }}
del {{ color: #ff8b7a; }}
</style></head>
<body><main>
<p>Private project · {PROJECT_PATH}</p>
<h1>{BAD_DEPLOY_TAG}</h1>
<p class="sha">{BAD_DEPLOY_SHA}</p>
<p>Dropped the null-price guard. Production deploy of this tag correlates with catalog 500s.</p>
<pre>@@ pricing.py
<del>-    if product.get("price") is None:
-        return 0</del>
     return product["price"] * product["qty"]</pre>
<h2>Previous</h2>
<pre>{PREVIOUS_FILE}</pre>
<h2>At tag</h2>
<pre>{BAD_FILE}</pre>
</main></body></html>"""

    return app


def main() -> None:
    public = os.environ.get("GITLAB_PUBLIC_URL", "http://localhost:8929")
    app = create_app(
        read_token=os.environ.get("GITLAB_READ_TOKEN", "glpat-read-demo"),
        write_token=os.environ.get("GITLAB_WRITE_TOKEN", "glpat-write-demo"),
        public_base=public,
        webhook_url=os.environ.get("GITLAB_WEBHOOK_URL", "http://agent:8080/api/gitlab/webhook"),
        webhook_token=os.environ.get("GITLAB_WEBHOOK_TOKEN", "demo-webhook"),
    )
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8929")))
