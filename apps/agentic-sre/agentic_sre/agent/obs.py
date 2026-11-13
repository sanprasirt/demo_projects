import re
from urllib.parse import quote

import httpx


class ObsClient:
    def __init__(self, prometheus_url: str, loki_url: str, tempo_url: str, grafana_url: str, client: httpx.Client | None = None):
        self.prometheus_url = prometheus_url.rstrip("/")
        self.loki_url = loki_url.rstrip("/")
        self.tempo_url = tempo_url.rstrip("/")
        self.grafana_url = grafana_url.rstrip("/")
        self._client = client or httpx.Client(timeout=8.0, trust_env=False)

    def promql(self, query: str) -> dict:
        response = self._client.get(self.prometheus_url + "/api/v1/query", params={"query": query})
        response.raise_for_status()
        body = response.json()
        series = body.get("data", {}).get("result", [])
        parts = []
        value = None
        for item in series[:6]:
            metric = item.get("metric") or {}
            labels = ",".join(f"{key}={val}" for key, val in metric.items() if key != "__name__")
            raw = item.get("value", [None, None])[1]
            parts.append(f"{labels or metric.get('__name__', 'series')}={raw}")
            if value is None and raw is not None:
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    value = None
        summary = "; ".join(parts) if parts else "no series"
        return {
            "summary": summary,
            "value": value,
            "link": explore(self.grafana_url, "prometheus", query),
        }

    def logql(self, query: str) -> dict:
        import time

        end = time.time()
        start = end - 900
        response = self._client.get(
            self.loki_url + "/loki/api/v1/query_range",
            params={"query": query, "start": int(start * 1e9), "end": int(end * 1e9), "limit": 20},
        )
        response.raise_for_status()
        streams = response.json().get("data", {}).get("result", [])
        lines = []
        trace_id = ""
        for stream in streams:
            for _, line in stream.get("values", [])[:8]:
                lines.append(line)
                if not trace_id:
                    match = re.search(r"trace_id=([0-9a-f]{8,32})", line)
                    if match:
                        trace_id = match.group(1)
        summary = lines[0] if lines else "no log lines"
        if len(lines) > 1:
            summary = f"{len(lines)} lines; newest: {lines[0]}"
        return {"summary": summary, "lines": lines[:8], "trace_id": trace_id, "link": explore(self.grafana_url, "loki", query)}

    def traceql(self, query: str) -> dict:
        response = self._client.get(self.tempo_url + "/api/search", params={"q": query, "limit": 5})
        response.raise_for_status()
        body = response.json()
        traces = body.get("traces") or []
        if not traces:
            response = self._client.get(self.tempo_url + "/api/search", params={"limit": 5})
            response.raise_for_status()
            traces = response.json().get("traces") or []
        if not traces:
            return {"summary": "no traces", "trace_id": "", "link": explore(self.grafana_url, "tempo", query)}
        first = traces[0]
        trace_id = first.get("traceID") or first.get("traceId") or ""
        name = first.get("rootTraceName") or first.get("rootServiceName") or "trace"
        return {
            "summary": f"{name} trace_id={trace_id}",
            "trace_id": trace_id,
            "link": f"{self.grafana_url}/explore?schemaVersion=1&orgId=1&panes="
            + quote('{"q":{"datasource":"tempo","queries":[{"query":"%s","queryType":"traceql"}]}}' % query),
        }


def explore(grafana: str, datasource: str, expr: str) -> str:
    import json

    pane = {"datasource": datasource, "queries": [{"refId": "A", "expr": expr}]}
    if datasource == "tempo":
        pane["queries"] = [{"refId": "A", "query": expr, "queryType": "traceql"}]
    return f"{grafana}/explore?schemaVersion=1&orgId=1&panes={quote(json.dumps({'q': pane}))}"
