from agentic_sre.kpis import compute_kpis


def test_kpi_clocks():
    kpis = compute_kpis(
        started_at=100.0,
        first_hypothesis_at=102.5,
        root_cause_at=103.0,
        evidence_count=4,
        writes_blocked=1,
    )
    assert kpis == {
        "time_to_first_hypothesis_s": 2.5,
        "time_to_root_cause_s": 3.0,
        "evidence_count": 4,
        "writes_blocked": 1,
    }
    empty = compute_kpis(
        started_at=1,
        first_hypothesis_at=None,
        root_cause_at=None,
        evidence_count=0,
        writes_blocked=0,
    )
    assert empty["time_to_first_hypothesis_s"] is None
    assert empty["writes_blocked"] == 0
