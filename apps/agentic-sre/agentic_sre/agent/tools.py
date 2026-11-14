import json

import httpx

READ_TOOLS = {
    "promql_query",
    "logql_query",
    "traceql_query",
    "gitlab_read",
    "get_runbook",
    "pg_activity",
    "pg_top_statements",
}
WRITE_TOOLS = {
    "gitlab_open_revert_mr",
    "set_failmode",
    "pg_terminate_backend",
    "pg_cancel_query",
    "pg_create_index",
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "promql_query",
            "description": "Run a PromQL instant query against Prometheus.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "logql_query",
            "description": "Run a LogQL range query against Loki.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "traceql_query",
            "description": "Search Tempo with a TraceQL query.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gitlab_read",
            "description": "Read commits, merge requests, pipelines, or deployments.",
            "parameters": {
                "type": "object",
                "properties": {"what": {"type": "string", "enum": ["commits", "merge_requests", "pipelines", "deployments"]}},
                "required": ["what"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_runbook",
            "description": "Fetch a runbook by id.",
            "parameters": {
                "type": "object",
                "properties": {"runbook_id": {"type": "string"}},
                "required": ["runbook_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pg_activity",
            "description": "Read pg_stat_activity: active and waiting queries, blocking pids, and wait events.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pg_top_statements",
            "description": "Read pg_stat_statements ordered by total or mean execution time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_by": {"type": "string", "enum": ["total_exec_time", "mean_exec_time"]},
                },
            },
        },
    },
]

_http = httpx.Client(timeout=10.0, trust_env=False)


def run_read(runtime, name: str, arguments: dict) -> dict:
    try:
        if name == "promql_query":
            found = runtime.obs.promql(arguments.get("query", ""))
            return {"kind": "promql", "query": arguments.get("query", ""), **found}
        if name == "logql_query":
            found = runtime.obs.logql(arguments.get("query", ""))
            return {"kind": "logql", "query": arguments.get("query", ""), **found}
        if name == "traceql_query":
            found = runtime.obs.traceql(arguments.get("query", ""))
            return {"kind": "traceql", "query": arguments.get("query", ""), **found}
        if name == "gitlab_read":
            return _gitlab_read(runtime, arguments.get("what", "deployments"))
        if name == "get_runbook":
            return _runbook(runtime, arguments.get("runbook_id", ""))
        if name == "pg_activity":
            return runtime.pg.activity()
        if name == "pg_top_statements":
            return runtime.pg.top_statements(arguments.get("order_by") or "total_exec_time")
    except Exception as exc:
        return {"kind": name, "query": json.dumps(arguments), "summary": f"tool failed: {exc}", "link": ""}
    return {"kind": name, "query": "", "summary": "tool returned nothing", "link": ""}


def run_write(runtime, step: dict, incident_id: str) -> dict:
    action = step["action"]
    params = step.get("params") or {}
    if action == "set_failmode":
        service = params["service"]
        url = runtime.settings.admin_urls[service]
        response = _http.post(
            url,
            headers={"X-Admin-Token": runtime.settings.admin_token},
            json={"mode": params.get("mode", "off"), "note": f"incident {incident_id}"},
        )
        response.raise_for_status()
        return {"ok": True, "summary": f"{service} fail mode set to {params.get('mode', 'off')}", "url": url}
    if action == "gitlab_open_revert_mr":
        mr = runtime.gitlab.open_revert_mr(
            sha=params["sha"],
            ref=params["ref"],
            source_branch=params["source_branch"],
            target_branch=params.get("target_branch", "main"),
            title=f"Revert {params['ref']} ({incident_id})",
            description=(
                f"Opened by the Day-2 agent for incident {incident_id}.\n\n"
                f"Bad SHA `{params['sha']}` was deployed to production as `{params['ref']}`."
            ),
        )
        return {"ok": True, "summary": f"opened MR !{mr['iid']}", "url": mr.get("web_url", "")}
    if action == "pg_terminate_backend":
        result = runtime.pg.terminate_backend(
            pid=params.get("pid"),
            application_name=params.get("application_name"),
        )
        return {"ok": True, "summary": result["summary"], "url": result.get("link", "")}
    if action == "pg_cancel_query":
        result = runtime.pg.cancel_query(
            pid=params.get("pid"),
            application_name=params.get("application_name"),
        )
        return {"ok": True, "summary": result["summary"], "url": result.get("link", "")}
    if action == "pg_create_index":
        result = runtime.pg.create_index(params.get("statement") or "")
        return {"ok": True, "summary": result["summary"], "url": result.get("link", "")}
    raise ValueError(f"unsupported write {action}")


def _gitlab_read(runtime, what: str) -> dict:
    if what == "commits":
        rows = runtime.gitlab.list_commits()
    elif what == "merge_requests":
        rows = runtime.gitlab.list_merge_requests()
    elif what == "pipelines":
        rows = runtime.gitlab.list_pipelines()
    else:
        what = "deployments"
        rows = runtime.gitlab.list_deployments()
    if not rows:
        return {"kind": "gitlab", "query": what, "summary": f"no {what}", "link": runtime.gitlab.public_url}
    first = rows[0]
    sha = first.get("sha") or first.get("id") or ""
    ref = first.get("ref") or first.get("title") or ""
    status = first.get("status") or first.get("state") or ""
    summary = f"{what} {status} ref={ref} sha={sha}".strip()
    link = runtime.gitlab.commit_url(sha) if sha and what != "merge_requests" else first.get("web_url") or runtime.gitlab.public_url
    return {"kind": "gitlab", "query": what, "summary": summary, "commit_sha": sha, "link": link}


def _runbook(runtime, runbook_id: str) -> dict:
    runbook = runtime.runbooks.get(runbook_id)
    if runbook is None:
        return {"kind": "runbook", "query": runbook_id, "summary": f"unknown runbook {runbook_id}", "link": ""}
    steps = ", ".join(step["id"] for step in runbook.steps)
    return {
        "kind": "runbook",
        "query": runbook.id,
        "summary": f"{runbook.title}. Steps: {steps}",
        "link": "",
    }
