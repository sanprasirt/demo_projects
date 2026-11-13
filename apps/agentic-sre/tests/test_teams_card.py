import json

from agentic_sre.agent.teams import build_incident_card
from agentic_sre.scenarios import BAD_DEPLOY_SHA


def test_incident_card_shape():
    card = build_incident_card(
        summary="Catalog 5xx rate is high after deploy",
        hypothesis=f"NullPrice after {BAD_DEPLOY_SHA}",
        evidence=[
            {
                "id": "e1",
                "kind": "promql",
                "summary": "catalog 5xx=4.5",
                "query": 'sum(rate(demo_http_requests_total{service="catalog",status=~"5.."}[1m]))',
                "link": "http://localhost:3000/explore",
            },
            {
                "id": "e2",
                "kind": "logql",
                "summary": "NullPrice",
                "query": '{service="catalog"} |= "ERROR"',
                "trace_id": "abc123def4567890aaaaaaaaaaaaaaaa",
            },
            {
                "id": "e4",
                "kind": "gitlab",
                "summary": "deployment success",
                "commit_sha": BAD_DEPLOY_SHA,
            },
        ],
        links=[("Grafana", "http://localhost:3000/d/day2"), ("GitLab", "http://localhost:8929/shop/day2-demo")],
        approve_url="http://localhost:8080/?incident=inc-1&step=open-revert-mr&intent=approve",
        reject_url="http://localhost:8080/?incident=inc-1&step=open-revert-mr&intent=reject",
    )
    assert card["type"] == "message"
    attachment = card["attachments"][0]
    assert attachment["contentType"] == "application/vnd.microsoft.card.adaptive"
    content = attachment["content"]
    assert content["type"] == "AdaptiveCard"
    assert content["version"] == "1.4"
    actions = content["actions"]
    assert [item["type"] for item in actions] == ["Action.OpenUrl", "Action.OpenUrl"]
    assert [item["title"] for item in actions] == ["Approve", "Reject"]
    assert actions[0]["url"].endswith("intent=approve")
    assert actions[1]["url"].endswith("intent=reject")
    blob = json.dumps(content)
    assert "Hypothesis" in blob
    assert BAD_DEPLOY_SHA in blob
    assert "trace_id=abc123def4567890aaaaaaaaaaaaaaaa" in blob
    assert "promql" in blob
    assert "Grafana" in blob
