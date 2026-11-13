"""Canonical bad-deploy records shared by the mock GitLab and the seed script."""

from agentic_sre.scenarios import (
    BAD_DEPLOY_SHA,
    BAD_DEPLOY_SHORT,
    BAD_DEPLOY_TAG,
    BAD_DEPLOY_TITLE,
    DEPLOYMENT_ID,
    PIPELINE_ID,
    PROJECT_ID,
    PROJECT_PATH,
)

BAD_FILE = """def unit_price(product):
    # catalog v1.4.2 dropped the None guard. A null price now raises.
    return product["price"] * product["qty"]
"""

PREVIOUS_FILE = """def unit_price(product):
    if product.get("price") is None:
        return 0
    return product["price"] * product["qty"]
"""


def project(public_base: str) -> dict:
    base = public_base.rstrip("/")
    return {
        "id": PROJECT_ID,
        "name": "day2-demo",
        "path": "day2-demo",
        "path_with_namespace": PROJECT_PATH,
        "visibility": "private",
        "web_url": f"{base}/{PROJECT_PATH}",
        "default_branch": "main",
    }


def commits(public_base: str, created_at: str) -> list[dict]:
    base = public_base.rstrip("/")
    return [
        {
            "id": BAD_DEPLOY_SHA,
            "short_id": BAD_DEPLOY_SHORT,
            "title": BAD_DEPLOY_TITLE,
            "message": BAD_DEPLOY_TITLE + "\n",
            "author_name": "day2-bot",
            "created_at": created_at,
            "parent_ids": ["a11ce0d0a11ce0d0a11ce0d0a11ce0d0a11ce0d0"],
            "web_url": f"{base}/{PROJECT_PATH}/-/commit/{BAD_DEPLOY_SHA}",
        },
        {
            "id": "a11ce0d0a11ce0d0a11ce0d0a11ce0d0a11ce0d0",
            "short_id": "a11ce0d0a11c",
            "title": "catalog: keep a guard around null prices",
            "message": "catalog: keep a guard around null prices\n",
            "author_name": "day2-bot",
            "created_at": "2026-11-01T09:00:00Z",
            "parent_ids": [],
            "web_url": f"{base}/{PROJECT_PATH}/-/commit/a11ce0d0a11ce0d0a11ce0d0a11ce0d0a11ce0d0",
        },
    ]


def pipelines(public_base: str, created_at: str) -> list[dict]:
    base = public_base.rstrip("/")
    return [
        {
            "id": PIPELINE_ID,
            "sha": BAD_DEPLOY_SHA,
            "ref": BAD_DEPLOY_TAG,
            "status": "success",
            "source": "push",
            "created_at": created_at,
            "web_url": f"{base}/{PROJECT_PATH}/-/pipelines/{PIPELINE_ID}",
        }
    ]


def deployments(public_base: str, created_at: str) -> list[dict]:
    base = public_base.rstrip("/")
    return [
        {
            "id": DEPLOYMENT_ID,
            "status": "success",
            "ref": BAD_DEPLOY_TAG,
            "sha": BAD_DEPLOY_SHA,
            "created_at": created_at,
            "updated_at": created_at,
            "environment": {"name": "production", "slug": "production"},
            "deployable": {
                "id": 100,
                "name": "deploy-catalog",
                "status": "success",
                "pipeline": {"id": PIPELINE_ID, "sha": BAD_DEPLOY_SHA, "ref": BAD_DEPLOY_TAG},
            },
            "web_url": f"{base}/{PROJECT_PATH}/-/environments/production/deployments/{DEPLOYMENT_ID}",
        }
    ]


def tags() -> list[dict]:
    return [
        {
            "name": BAD_DEPLOY_TAG,
            "target": BAD_DEPLOY_SHA,
            "message": "catalog production",
        }
    ]
