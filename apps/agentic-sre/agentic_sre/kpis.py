def _seconds(start: float | None, end: float | None) -> float | None:
    if start is None or end is None:
        return None
    return round(max(0.0, end - start), 2)


def compute_kpis(
    *,
    started_at: float | None,
    first_hypothesis_at: float | None,
    root_cause_at: float | None,
    evidence_count: int,
    writes_blocked: int,
) -> dict:
    return {
        "time_to_first_hypothesis_s": _seconds(started_at, first_hypothesis_at),
        "time_to_root_cause_s": _seconds(started_at, root_cause_at),
        "evidence_count": evidence_count,
        "writes_blocked": writes_blocked,
    }
