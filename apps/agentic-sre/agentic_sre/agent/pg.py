"""Read-only Postgres inspection, plus the approval-gated writes."""

import logging

import psycopg
from psycopg.rows import dict_row

from agentic_sre.agent.pg_fixture import STATE
from agentic_sre.db import CREATE_INDEX_SQL
from agentic_sre.masking import mask_sql_literals

log = logging.getLogger("agentic_sre.pg")

ALLOWED_APP_NAMES = {"sre-lock", "sre-hold", "sre-lock-wait"}
ORDER_COLUMNS = {
    "total_exec_time": "total_exec_time",
    "mean_exec_time": "mean_exec_time",
}


def format_activity(rows: list[dict]) -> dict:
    masked = []
    blocking: list[int] = []
    waiting = 0
    for row in rows:
        query = mask_sql_literals(row.get("query") or "")
        pids = [int(pid) for pid in (row.get("blocking_pids") or []) if pid is not None]
        waiting_now = bool(pids) or (row.get("wait_event_type") or "") == "Lock"
        if waiting_now:
            waiting += 1
        blocking.extend(pids)
        masked.append(
            {
                "pid": int(row.get("pid") or 0),
                "application_name": row.get("application_name") or "",
                "state": row.get("state") or "",
                "wait_event_type": row.get("wait_event_type") or "",
                "wait_event": row.get("wait_event") or "",
                "blocking_pids": pids,
                "query": query,
            }
        )
    unique = sorted(set(blocking))
    ranked = sorted(
        masked,
        key=lambda item: (not item["blocking_pids"], item["wait_event_type"] != "Lock", item["state"] != "active"),
    )
    lines = []
    for item in ranked[:6]:
        if not (item["blocking_pids"] or item["wait_event_type"] or item["state"] in {"active", "idle in transaction"}):
            continue
        lines.append(
            f"pid={item['pid']} app={item['application_name'] or '-'} state={item['state'] or '-'} "
            f"wait={item['wait_event_type'] or '-'}/{item['wait_event'] or '-'} "
            f"blocking={item['blocking_pids'] or '-'} query={item['query'][:90]}"
        )
    sample = ranked[0]["query"] if ranked else ""
    summary = f"sessions={len(masked)} waiting={waiting} blocking_pids={unique or 'none'}"
    if lines:
        summary = summary + "; " + " | ".join(lines)
    return {
        "kind": "pg_activity",
        "query": sample[:300],
        "summary": summary[:700],
        "blocking_pids": unique,
        "waiting": waiting,
        "link": "",
    }


def format_statements(rows: list[dict], order_by: str) -> dict:
    masked = []
    for row in rows:
        masked.append(
            {
                "query": mask_sql_literals(row.get("query") or "")[:180],
                "calls": int(row.get("calls") or 0),
                "total_ms": round(float(row.get("total_exec_time") or 0), 1),
                "mean_ms": round(float(row.get("mean_exec_time") or 0), 1),
            }
        )
    parts = [f"mean_ms={item['mean_ms']} calls={item['calls']} {item['query'][:80]}" for item in masked[:5]]
    summary = f"top by {order_by}: " + " | ".join(parts) if parts else "pg_stat_statements returned no rows"
    return {
        "kind": "pg_statements",
        "query": masked[0]["query"] if masked else "",
        "summary": summary[:700],
        "link": "",
    }


class PgClient:
    def __init__(self, read_dsn: str, write_dsn: str, grafana_url: str = ""):
        self.read_dsn = read_dsn or ""
        self.write_dsn = write_dsn or ""
        self.grafana_url = (grafana_url or "").rstrip("/")
        self.fixture = self.read_dsn.startswith("fixture://")
        self.scenario = self.read_dsn.removeprefix("fixture://") if self.fixture else ""

    def activity(self) -> dict:
        if self.fixture:
            return self._with_link(format_activity(self._fixture_activity_rows()))
        if not self.read_dsn:
            return self._empty("pg_activity", "postgres read DSN is not set")
        with self._connect(self.read_dsn) as conn:
            rows = conn.execute(
                """
                SELECT
                  a.pid,
                  COALESCE(a.application_name, '') AS application_name,
                  COALESCE(a.state, '') AS state,
                  COALESCE(a.wait_event_type, '') AS wait_event_type,
                  COALESCE(a.wait_event, '') AS wait_event,
                  COALESCE(pg_blocking_pids(a.pid), ARRAY[]::int[]) AS blocking_pids,
                  left(COALESCE(a.query, ''), 300) AS query
                FROM pg_stat_activity AS a
                WHERE (a.datname = current_database() OR a.application_name LIKE 'sre-%%')
                  AND a.pid <> pg_backend_pid()
                ORDER BY a.state NULLS LAST, a.pid
                LIMIT 30
                """
            ).fetchall()
        return self._with_link(format_activity([dict(row) for row in rows]))

    def top_statements(self, order_by: str = "total_exec_time") -> dict:
        column = ORDER_COLUMNS.get(order_by or "", "total_exec_time")
        if self.fixture:
            return self._with_link(format_statements(self._fixture_statement_rows(), column))
        if not self.read_dsn:
            return self._empty("pg_statements", "postgres read DSN is not set")
        with self._connect(self.read_dsn) as conn:
            rows = conn.execute(
                f"""
                SELECT left(query, 240) AS query, calls, total_exec_time, mean_exec_time, rows
                FROM pg_stat_statements
                WHERE query NOT ILIKE '%%pg_stat_statements%%'
                  AND query NOT ILIKE '%%pg_stat_activity%%'
                ORDER BY {column} DESC
                LIMIT 8
                """
            ).fetchall()
        return self._with_link(format_statements([dict(row) for row in rows], column))

    def terminate_backend(self, *, pid: int | None = None, application_name: str | None = None) -> dict:
        self._check_target(pid, application_name)
        if self.fixture:
            return self._fixture_signal("terminate", pid, application_name)
        return self._signal("pg_terminate_backend", pid=pid, application_name=application_name, verb="terminated")

    def cancel_query(self, *, pid: int | None = None, application_name: str | None = None) -> dict:
        self._check_target(pid, application_name)
        if self.fixture:
            snap = STATE.snapshot()
            STATE.cancelled.append(application_name or str(pid or ""))
            return self._with_link(
                {
                    "kind": "pg_cancel_query",
                    "query": "",
                    "summary": f"cancelled fixture target {application_name or pid}",
                    "link": "",
                    "blocking_pids": [snap["blocking_pid"]] if snap["lock_waits"] else [],
                }
            )
        return self._signal("pg_cancel_backend", pid=pid, application_name=application_name, verb="cancelled")

    def create_index(self, statement: str) -> dict:
        normalized = " ".join((statement or "").split())
        if normalized != CREATE_INDEX_SQL:
            raise ValueError("refusing SQL that is not the approved orders index build")
        if self.fixture:
            STATE.mark_index()
            return self._with_link(
                {
                    "kind": "pg_create_index",
                    "query": mask_sql_literals(normalized),
                    "summary": "created orders_sku_created_idx concurrently",
                    "link": "",
                }
            )
        if not self.write_dsn:
            raise RuntimeError("postgres write DSN is not set")
        with self._connect(self.write_dsn, autocommit=True) as conn:
            conn.execute("SET lock_timeout = '20s'")
            conn.execute("SET ROLE shop_app")
            conn.execute(normalized)
            try:
                conn.execute("SELECT pg_stat_statements_reset()")
            except psycopg.Error:
                log.warning("pg_stat_statements_reset failed", exc_info=True)
            conn.execute("RESET ROLE")
        return self._with_link(
            {
                "kind": "pg_create_index",
                "query": normalized,
                "summary": "created orders_sku_created_idx concurrently and reset statement stats",
                "link": "",
            }
        )

    def _signal(self, fn: str, *, pid, application_name, verb: str) -> dict:
        if not self.write_dsn:
            raise RuntimeError("postgres write DSN is not set")
        with self._connect(self.write_dsn, autocommit=True) as conn:
            if pid:
                rows = conn.execute(
                    f"SELECT %s::int AS pid, {fn}(%s) AS ok",
                    (int(pid), int(pid)),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT pid, {fn}(pid) AS ok
                    FROM pg_stat_activity
                    WHERE application_name = %s
                      AND pid <> pg_backend_pid()
                    """,
                    (application_name,),
                ).fetchall()
        done = [int(row["pid"]) for row in rows if row["ok"]]
        target = application_name or pid
        summary = f"{verb} {len(done)} backend(s) for {target}: {done or 'none'}"
        return self._with_link({"kind": fn, "query": "", "summary": summary, "link": "", "pids": done})

    def _fixture_signal(self, kind: str, pid, application_name) -> dict:
        target = application_name or (str(pid) if pid else "")
        if target == "sre-lock" or self.scenario == "lock":
            STATE.clear_lock(target or kind)
        elif target == "sre-hold" or self.scenario == "connections":
            STATE.clear_connections(target or kind)
        else:
            STATE.clear_lock(target or kind)
        snap = STATE.snapshot()
        return self._with_link(
            {
                "kind": "pg_terminate_backend" if kind == "terminate" else "pg_cancel_query",
                "query": "",
                "summary": f"{kind} fixture target {target or 'blocker'}; lock_waits={snap['lock_waits']}",
                "link": "",
                "pids": [snap["blocking_pid"]],
            }
        )

    def _fixture_activity_rows(self) -> list[dict]:
        snap = STATE.snapshot()
        if self.scenario == "lock" and snap["lock_waits"] > 0:
            return [
                {
                    "pid": 4242,
                    "application_name": "sre-lock",
                    "state": "idle in transaction",
                    "wait_event_type": "",
                    "wait_event": "",
                    "blocking_pids": [],
                    "query": "SELECT stock FROM products WHERE sku = 'locked-sku' FOR UPDATE",
                },
                {
                    "pid": 4243,
                    "application_name": "sre-lock-wait",
                    "state": "active",
                    "wait_event_type": "Lock",
                    "wait_event": "tuple",
                    "blocking_pids": [4242],
                    "query": "SELECT stock FROM products WHERE sku = 'mug' AND qty > 2 FOR UPDATE",
                },
            ]
        if self.scenario == "connections" and snap["connection_ratio"] > 0.75:
            return [
                {
                    "pid": 5100 + index,
                    "application_name": "sre-hold",
                    "state": "idle",
                    "wait_event_type": "",
                    "wait_event": "",
                    "blocking_pids": [],
                    "query": "SELECT 1",
                }
                for index in range(4)
            ]
        return [
            {
                "pid": 11,
                "application_name": "checkout",
                "state": "idle",
                "wait_event_type": "",
                "wait_event": "",
                "blocking_pids": [],
                "query": "SELECT /* orders_by_sku */ count(*) FROM orders WHERE sku = $1",
            }
        ]

    def _fixture_statement_rows(self) -> list[dict]:
        snap = STATE.snapshot()
        mean = 420.0 if snap["slow_seconds"] > 0.08 else 1.2
        return [
            {
                "query": "SELECT /* orders_by_sku */ count(md5(o.note || g.n::text)) FROM orders AS o WHERE o.sku = $1",
                "calls": 40,
                "total_exec_time": mean * 40,
                "mean_exec_time": mean,
            },
            {
                "query": "INSERT INTO orders (sku, qty, note) VALUES ($1, $2, $3)",
                "calls": 80,
                "total_exec_time": 40.0,
                "mean_exec_time": 0.5,
            },
        ]

    def _check_target(self, pid, application_name) -> None:
        if application_name:
            if application_name not in ALLOWED_APP_NAMES:
                raise ValueError("application_name is not an injectable demo session")
            return
        if pid is None:
            raise ValueError("pid or application_name is required")
        if int(pid) <= 0:
            raise ValueError("pid must be positive")

    def _connect(self, dsn: str, *, autocommit: bool = True):
        return psycopg.connect(dsn, autocommit=autocommit, connect_timeout=5, row_factory=dict_row)

    def _with_link(self, payload: dict) -> dict:
        if self.grafana_url:
            payload["link"] = self.grafana_url + "/d/postgres/postgresql"
        return payload

    def _empty(self, kind: str, summary: str) -> dict:
        return self._with_link({"kind": kind, "query": "", "summary": summary, "link": ""})
