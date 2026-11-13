from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Runbook:
    raw: dict

    @property
    def id(self) -> str:
        return self.raw["id"]

    @property
    def title(self) -> str:
        return self.raw["title"]

    @property
    def steps(self) -> list[dict]:
        return self.raw["steps"]

    def public(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "markdown": self.raw.get("markdown", ""),
            "steps": [
                {
                    "id": step["id"],
                    "title": step["title"],
                    "action": step["action"],
                    "approval_required": bool(step.get("approval_required")),
                }
                for step in self.steps
            ],
        }


class RunbookLibrary:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.runbooks = []
        for path in sorted(self.directory.glob("*.yaml")):
            self.runbooks.append(Runbook(yaml.safe_load(path.read_text(encoding="utf-8"))))

    def get(self, runbook_id: str) -> Runbook | None:
        for runbook in self.runbooks:
            if runbook.id == runbook_id:
                return runbook
        return None

    def match(self, *, alertname: str, text: str) -> Runbook | None:
        best = None
        best_score = 0
        blob = (text or "").lower()
        for runbook in self.runbooks:
            rules = runbook.raw.get("match") or {}
            score = 0
            if alertname and alertname in rules.get("alertnames", []):
                score += 10
            for keyword in rules.get("keywords", []):
                if keyword.lower() in blob:
                    score += 1
            if score > best_score:
                best = runbook
                best_score = score
        return best
