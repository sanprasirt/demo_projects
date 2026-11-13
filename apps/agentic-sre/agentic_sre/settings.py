import os
from dataclasses import dataclass

from agentic_sre.paths import NEMO, RUNBOOKS


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


@dataclass
class Settings:
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    prometheus_url: str
    loki_url: str
    tempo_url: str
    gitlab_url: str
    gitlab_public_url: str
    gitlab_project_id: str
    gitlab_project_path: str
    gitlab_read_token: str
    gitlab_write_token: str
    gitlab_webhook_token: str
    teams_webhook_url: str
    agent_public_url: str
    grafana_public_url: str
    admin_token: str
    catalog_admin_url: str
    checkout_admin_url: str
    gateway_admin_url: str
    catalog_probe_url: str
    checkout_probe_url: str
    runbooks_dir: str
    nemo_dir: str
    enable_nemo: bool

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            llm_base_url=_env("LLM_BASE_URL", "http://127.0.0.1:8000/v1"),
            llm_model=_env("LLM_MODEL", "mock-sre"),
            llm_api_key=_env("LLM_API_KEY", "dummy"),
            prometheus_url=_env("PROMETHEUS_URL", "http://127.0.0.1:9090"),
            loki_url=_env("LOKI_URL", "http://127.0.0.1:3100"),
            tempo_url=_env("TEMPO_URL", "http://127.0.0.1:3200"),
            gitlab_url=_env("GITLAB_URL", "http://127.0.0.1:8929"),
            gitlab_public_url=_env("GITLAB_PUBLIC_URL", "http://localhost:8929"),
            gitlab_project_id=_env("GITLAB_PROJECT_ID", "1"),
            gitlab_project_path=_env("GITLAB_PROJECT_PATH", "shop/day2-demo"),
            gitlab_read_token=_env("GITLAB_READ_TOKEN", "glpat-read-demo"),
            gitlab_write_token=_env("GITLAB_WRITE_TOKEN", "glpat-write-demo"),
            gitlab_webhook_token=_env("GITLAB_WEBHOOK_TOKEN", "demo-webhook"),
            teams_webhook_url=_env("TEAMS_WEBHOOK_URL", "http://127.0.0.1:8090/webhook"),
            agent_public_url=_env("AGENT_PUBLIC_URL", "http://localhost:8080"),
            grafana_public_url=_env("GRAFANA_PUBLIC_URL", "http://localhost:3000"),
            admin_token=_env("ADMIN_TOKEN", "demo-admin"),
            catalog_admin_url=_env("CATALOG_ADMIN_URL", "http://127.0.0.1:8002/admin/failmode"),
            checkout_admin_url=_env("CHECKOUT_ADMIN_URL", "http://127.0.0.1:8003/admin/failmode"),
            gateway_admin_url=_env("GATEWAY_ADMIN_URL", "http://127.0.0.1:8001/admin/failmode"),
            catalog_probe_url=_env("CATALOG_PROBE_URL", "http://127.0.0.1:8002/products"),
            checkout_probe_url=_env("CHECKOUT_PROBE_URL", "http://127.0.0.1:8003/health"),
            runbooks_dir=_env("RUNBOOKS_DIR", str(RUNBOOKS)),
            nemo_dir=_env("NEMO_DIR", str(NEMO)),
            enable_nemo=_env("ENABLE_NEMO", "1") not in {"0", "false", "False"},
        )

    @property
    def admin_urls(self) -> dict[str, str]:
        return {
            "catalog": self.catalog_admin_url,
            "checkout": self.checkout_admin_url,
            "gateway": self.gateway_admin_url,
        }

    @property
    def probe_urls(self) -> dict[str, str]:
        return {
            "catalog": self.catalog_probe_url,
            "checkout": self.checkout_probe_url,
        }
