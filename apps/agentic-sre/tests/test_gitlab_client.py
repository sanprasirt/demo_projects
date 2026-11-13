import pytest
from fastapi.testclient import TestClient

from agentic_sre.agent.gitlab_client import GitLabClient
from agentic_sre.scenarios import BAD_DEPLOY_SHA, BAD_DEPLOY_TAG
from agentic_sre.services.mock_gitlab import create_app


def _client():
    http = TestClient(create_app())
    gitlab = GitLabClient(
        "http://testserver",
        "glpat-read-demo",
        "glpat-write-demo",
        "1",
        public_url="http://localhost:8929",
        client=http,
    )
    return http, gitlab


def test_reads_seeded_bad_deploy_and_write_token_opens_mr():
    http, gitlab = _client()
    deployments = gitlab.list_deployments()
    assert deployments[0]["sha"] == BAD_DEPLOY_SHA
    assert deployments[0]["ref"] == BAD_DEPLOY_TAG
    assert deployments[0]["environment"]["name"] == "production"
    commits = gitlab.list_commits()
    assert commits[0]["id"] == BAD_DEPLOY_SHA
    pipelines = gitlab.list_pipelines()
    assert pipelines[0]["status"] == "success"
    denied = http.post(
        "/api/v4/projects/1/merge_requests",
        headers={"PRIVATE-TOKEN": "glpat-read-demo"},
        json={"source_branch": "x", "target_branch": "main", "title": "nope"},
    )
    assert denied.status_code == 403
    opened = gitlab.open_revert_mr(
        sha=BAD_DEPLOY_SHA,
        ref=BAD_DEPLOY_TAG,
        source_branch="revert-catalog-v1.4.2",
        target_branch="main",
        title="Revert catalog v1.4.2",
        description="incident",
    )
    assert opened["state"] == "opened"
    assert opened["iid"] == 1
    assert opened["web_url"].endswith("/-/merge_requests/1")
    listed = gitlab.list_merge_requests()
    assert listed[0]["title"] == "Revert catalog v1.4.2"


def test_missing_token_is_rejected():
    _, gitlab = _client()
    gitlab.read_token = ""
    with pytest.raises(Exception) as caught:
        gitlab.list_commits()
    assert caught.value.response.status_code in {401, 403}
