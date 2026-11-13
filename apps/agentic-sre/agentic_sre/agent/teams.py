import httpx


def build_incident_card(
    *,
    summary: str,
    hypothesis: str,
    evidence: list[dict],
    links: list[tuple[str, str]],
    approve_url: str,
    reject_url: str,
) -> dict:
    body = [
        {"type": "TextBlock", "text": "Day-2 incident", "weight": "Bolder", "color": "Attention", "size": "Large"},
        {"type": "TextBlock", "text": summary, "wrap": True},
        {"type": "TextBlock", "text": "Hypothesis", "weight": "Bolder", "separator": True},
        {"type": "TextBlock", "text": hypothesis or "Still investigating.", "wrap": True},
        {"type": "TextBlock", "text": "Evidence", "weight": "Bolder", "separator": True},
    ]
    if not evidence:
        body.append({"type": "TextBlock", "text": "No evidence yet.", "wrap": True, "isSubtle": True})
    for item in evidence[:8]:
        bits = [f"{item.get('id', '')} {item.get('kind', '')}: {item.get('summary', '')}"]
        if item.get("query"):
            bits.append(item["query"])
        if item.get("trace_id"):
            bits.append(f"trace_id={item['trace_id']}")
        if item.get("commit_sha"):
            bits.append(f"sha={item['commit_sha']}")
        body.append(
            {
                "type": "TextBlock",
                "text": "\n".join(bits),
                "wrap": True,
                "fontType": "Monospace",
                "size": "Small",
            }
        )
    for label, url in links:
        body.append({"type": "TextBlock", "text": f"[{label}]({url})", "wrap": True})
    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": body,
        "actions": [
            {"type": "Action.OpenUrl", "title": "Approve", "url": approve_url},
            {"type": "Action.OpenUrl", "title": "Reject", "url": reject_url},
        ],
    }
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card,
            }
        ],
    }


def build_update_card(*, title: str, text: str) -> dict:
    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "text": title, "weight": "Bolder"},
            {"type": "TextBlock", "text": text, "wrap": True},
        ],
    }
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card,
            }
        ],
    }


class TeamsClient:
    def __init__(self, webhook_url: str, client: httpx.Client | None = None):
        self.webhook_url = webhook_url
        self._client = client or httpx.Client(timeout=8.0, trust_env=False)

    def post(self, payload: dict) -> None:
        if not self.webhook_url:
            return
        response = self._client.post(self.webhook_url, json=payload)
        response.raise_for_status()
