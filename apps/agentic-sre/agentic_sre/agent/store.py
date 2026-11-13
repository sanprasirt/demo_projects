import threading
import time
import uuid
from datetime import datetime, timezone

from agentic_sre.kpis import compute_kpis


def _iso(moment: float | None = None) -> str:
    when = datetime.fromtimestamp(moment or time.time(), tz=timezone.utc)
    return when.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class IncidentStore:
    def __init__(self):
        self._lock = threading.Lock()
        self.incidents: dict[str, dict] = {}
        self.order: list[str] = []
        self.buffer: list[dict] = []

    def create(self, alert: dict, *, grafana_url: str, gitlab_url: str) -> dict:
        labels = alert.get("labels") or {}
        annotations = alert.get("annotations") or {}
        now = time.time()
        incident_id = "inc-" + uuid.uuid4().hex[:8]
        fingerprint = f"{labels.get('alertname', '')}|{alert.get('startsAt', '')}"
        record = {
            "id": incident_id,
            "fingerprint": fingerprint,
            "status": "investigating",
            "alertname": labels.get("alertname", ""),
            "service": labels.get("service", ""),
            "scenario": labels.get("scenario", ""),
            "summary": annotations.get("summary") or labels.get("alertname", "incident"),
            "description": annotations.get("description", ""),
            "started_at": now,
            "started_at_iso": _iso(now),
            "first_hypothesis_at": None,
            "root_cause_at": None,
            "hypothesis": "",
            "evidence": [],
            "timeline": [],
            "writes_blocked": 0,
            "pending_step": None,
            "postmortem": "",
            "runbook_id": "",
            "approvals": [],
            "once": set(),
            "grafana_url": grafana_url,
            "gitlab_url": gitlab_url,
            "error": "",
        }
        with self._lock:
            self.incidents[incident_id] = record
            self.order.append(incident_id)
            for item in self.buffer:
                self._append_timeline(record, item["kind"], item["text"], extra=item.get("extra") or {})
        self.timeline(incident_id, "alert", record["summary"])
        return self.get(incident_id)

    def by_fingerprint(self, fingerprint: str) -> dict | None:
        with self._lock:
            for record in self.incidents.values():
                if record["fingerprint"] == fingerprint:
                    return self._public(record)
        return None

    def get(self, incident_id: str) -> dict | None:
        with self._lock:
            record = self.incidents.get(incident_id)
            return None if record is None else self._public(record)

    def list(self) -> list[dict]:
        with self._lock:
            return [self._public(self.incidents[key]) for key in reversed(self.order)]

    def update(self, incident_id: str, **fields) -> None:
        with self._lock:
            record = self.incidents[incident_id]
            for key, value in fields.items():
                record[key] = value

    def mark_hypothesis(self, incident_id: str, text: str, *, accepted: bool) -> None:
        now = time.time()
        with self._lock:
            record = self.incidents[incident_id]
            record["hypothesis"] = text
            if record["first_hypothesis_at"] is None:
                record["first_hypothesis_at"] = now
            if accepted and record["root_cause_at"] is None:
                record["root_cause_at"] = now

    def add_evidence(self, incident_id: str, item: dict) -> dict:
        with self._lock:
            record = self.incidents[incident_id]
            stored = dict(item)
            stored["id"] = f"e{len(record['evidence']) + 1}"
            record["evidence"].append(stored)
            return dict(stored)

    def timeline(self, incident_id: str, kind: str, text: str, **extra) -> None:
        with self._lock:
            self._append_timeline(self.incidents[incident_id], kind, text, extra=extra)

    def once(self, incident_id: str, key: str) -> bool:
        with self._lock:
            seen = self.incidents[incident_id]["once"]
            if key in seen:
                return False
            seen.add(key)
            return True

    def block_write(self, incident_id: str, step_id: str, tool_name: str) -> None:
        if not self.once(incident_id, f"blocked:{step_id}"):
            return
        with self._lock:
            record = self.incidents[incident_id]
            record["writes_blocked"] += 1
            self._append_timeline(
                record,
                "write_blocked",
                f"{tool_name} blocked pending approval",
                extra={"step_id": step_id, "tool": tool_name},
            )

    def note_gitlab(self, event_name: str, payload: dict) -> None:
        text = _gitlab_text(event_name, payload)
        item = {"kind": "gitlab_webhook", "text": text, "extra": {"event": event_name}}
        with self._lock:
            self.buffer.append(item)
            self.buffer[:] = self.buffer[-20:]
            for record in self.incidents.values():
                if record["status"] in {"resolved", "rejected", "blocked"}:
                    continue
                marker = "gl:" + text
                if marker in record["once"]:
                    continue
                record["once"].add(marker)
                self._append_timeline(record, "gitlab_webhook", text, extra={"event": event_name})

    def note_resolved(self, alertname: str, text: str) -> None:
        with self._lock:
            for record in self.incidents.values():
                if record["alertname"] == alertname and record["status"] not in {"resolved", "rejected"}:
                    self._append_timeline(record, "alert_resolved", text)

    def _append_timeline(self, record: dict, kind: str, text: str, extra: dict | None = None) -> None:
        event = {"at": _iso(), "kind": kind, "text": text}
        if extra:
            event.update(extra)
        record["timeline"].append(event)

    def _public(self, record: dict) -> dict:
        kpis = compute_kpis(
            started_at=record["started_at"],
            first_hypothesis_at=record["first_hypothesis_at"],
            root_cause_at=record["root_cause_at"],
            evidence_count=len(record["evidence"]),
            writes_blocked=record["writes_blocked"],
        )
        return {
            "id": record["id"],
            "status": record["status"],
            "alertname": record["alertname"],
            "service": record["service"],
            "scenario": record["scenario"],
            "summary": record["summary"],
            "description": record["description"],
            "started_at": record["started_at_iso"],
            "hypothesis": record["hypothesis"],
            "evidence": list(record["evidence"]),
            "timeline": list(record["timeline"]),
            "pending_step": record["pending_step"],
            "postmortem": record["postmortem"],
            "runbook_id": record["runbook_id"],
            "approvals": list(record["approvals"]),
            "kpis": kpis,
            "grafana_url": record["grafana_url"],
            "gitlab_url": record["gitlab_url"],
            "error": record["error"],
        }


def _gitlab_text(event_name: str, payload: dict) -> str:
    if payload.get("object_kind") == "deployment" or "Deployment" in event_name:
        sha = payload.get("sha") or payload.get("short_sha") or ""
        ref = payload.get("ref") or ""
        env = payload.get("environment") or ""
        return f"deployment {payload.get('status', '')} env={env} ref={ref} sha={sha}".strip()
    attrs = payload.get("object_attributes") or {}
    if attrs:
        return f"pipeline {attrs.get('status', '')} ref={attrs.get('ref', '')} sha={attrs.get('sha', '')}".strip()
    return event_name or "gitlab event"
