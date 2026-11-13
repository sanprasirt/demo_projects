"""Create the private demo project, the bad catalog commit, tag, and deployment.

Works against the mock GitLab and against GitLab CE once GITLAB_WRITE_TOKEN can call the API.
"""

import os
import sys

import httpx

from agentic_sre.gitlab_seed import BAD_FILE
from agentic_sre.scenarios import BAD_DEPLOY_SHA, BAD_DEPLOY_TAG, BAD_DEPLOY_TITLE


def main() -> None:
    base = os.environ.get("GITLAB_URL", "http://127.0.0.1:8929").rstrip("/")
    token = os.environ["GITLAB_WRITE_TOKEN"]
    webhook = os.environ.get("AGENT_WEBHOOK_URL", "http://agent:8080/api/gitlab/webhook")
    hook_token = os.environ.get("GITLAB_WEBHOOK_TOKEN", "demo-webhook")
    client = httpx.Client(timeout=30.0, trust_env=False, headers={"PRIVATE-TOKEN": token})
    project = client.post(
        base + "/api/v4/projects",
        json={"name": "day2-demo", "path": "day2-demo", "namespace": "shop", "visibility": "private"},
    )
    project.raise_for_status()
    project_id = project.json()["id"]
    commit = client.post(
        f"{base}/api/v4/projects/{project_id}/repository/commits",
        json={
            "branch": "main",
            "commit_message": BAD_DEPLOY_TITLE,
            "actions": [{"action": "update", "file_path": "catalog/pricing.py", "content": BAD_FILE}],
        },
    )
    commit.raise_for_status()
    sha = commit.json().get("id", BAD_DEPLOY_SHA)
    tag = client.post(
        f"{base}/api/v4/projects/{project_id}/repository/tags",
        json={"tag_name": BAD_DEPLOY_TAG, "ref": sha, "message": "catalog production"},
    )
    tag.raise_for_status()
    deployment = client.post(
        f"{base}/api/v4/projects/{project_id}/deployments",
        json={"environment": "production", "sha": sha, "ref": BAD_DEPLOY_TAG, "tag": True, "status": "success"},
    )
    deployment.raise_for_status()
    hook = client.post(
        f"{base}/api/v4/projects/{project_id}/hooks",
        json={
            "url": webhook,
            "deployment_events": True,
            "pipeline_events": True,
            "token": hook_token,
        },
    )
    hook.raise_for_status()
    print(f"project={project_id} sha={sha} tag={BAD_DEPLOY_TAG} deployment={deployment.json().get('id')}")


if __name__ == "__main__":
    try:
        main()
    except KeyError as exc:
        print(f"missing {exc}", file=sys.stderr)
        sys.exit(2)
