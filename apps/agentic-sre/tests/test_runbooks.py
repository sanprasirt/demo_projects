from agentic_sre.agent.runbooks import RunbookLibrary
from agentic_sre.paths import RUNBOOKS
from agentic_sre.scenarios import BAD_DEPLOY_SHA


def test_matches_each_scenario():
    library = RunbookLibrary(RUNBOOKS)
    bad = library.match(alertname="CatalogHighErrorRate", text="catalog 5xx NullPrice")
    assert bad is not None
    assert bad.id == "bad-deploy"
    assert bad.steps[0]["approval_required"] is True
    assert bad.steps[0]["action"] == "gitlab_open_revert_mr"
    assert bad.steps[0]["params"]["sha"] == BAD_DEPLOY_SHA
    assert bad.steps[1]["approval_required"] is True
    assert bad.steps[2]["action"] == "verify"
    assert "null price" in bad.raw["markdown"].lower() or "Null" in bad.raw["markdown"] or "500" in bad.raw["markdown"]

    memory = library.match(alertname="ServiceMemoryHigh", text="leak")
    assert memory.id == "memory-leak"
    latency = library.match(alertname="DependencyLatencyHigh", text="orders-db")
    assert latency.id == "dependency-latency"
    assert library.match(alertname="UnknownAlert", text="nothing to see") is None
