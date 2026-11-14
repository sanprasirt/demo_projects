import os
import shutil
import subprocess
import time
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from agentic_sre.agent.pg import PgClient, format_activity
from agentic_sre.agent.pg_fixture import STATE
from agentic_sre.db import CREATE_INDEX_SQL
from agentic_sre.masking import mask_sql_literals
from agentic_sre.services.mock_llm import decide


def test_mask_sql_literals_hides_values():
    masked = mask_sql_literals("SELECT stock FROM products WHERE sku = 'mug' AND qty > 2")
    assert "mug" not in masked
    assert "2" not in masked.split(">")[-1]
    assert "?" in masked
    assert "products" in masked
    assert mask_sql_literals("SELECT stock FROM products WHERE sku = $1") .endswith("$1")


def test_activity_formatter_keeps_blocking_pid_and_masks_sql():
    payload = format_activity(
        [
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
    )
    assert payload["blocking_pids"] == [4242]
    assert payload["waiting"] == 1
    assert "4242" in payload["summary"]
    assert "Lock" in payload["summary"]
    assert "'mug'" not in payload["summary"]
    assert "'locked-sku'" not in payload["summary"]
    assert "sre-lock-wait" in payload["summary"]


def test_fixture_tools_and_rejected_sql():
    STATE.arm_lock()
    client = PgClient("fixture://lock", "fixture://lock", "http://grafana.example")
    activity = client.activity()
    assert activity["blocking_pids"] == [4242]
    assert activity["link"].endswith("/d/postgres/postgresql")
    assert "'mug'" not in activity["summary"]
    statements = client.top_statements("mean_exec_time")
    assert statements["kind"] == "pg_statements"
    assert "mean_ms=" in statements["summary"]
    with pytest.raises(ValueError):
        client.create_index("DROP TABLE orders")
    with pytest.raises(ValueError):
        client.terminate_backend(application_name="postgres")
    done = client.terminate_backend(application_name="sre-lock")
    assert "terminate" in done["summary"]
    assert STATE.snapshot()["lock_waits"] == 0
    client.create_index(CREATE_INDEX_SQL)
    assert STATE.snapshot()["index_created"] is True


def test_mock_llm_uses_pg_tools_for_database_alerts():
    messages = [{"role": "user", "content": "PHASE=investigate\nAlert: DBLockWaitsHigh\nlock"}]
    names = []
    for _ in range(8):
        choice = decide(messages, [{"type": "function"}])
        if not choice["tool_calls"]:
            break
        names.append(choice["tool_calls"][0]["name"])
        messages.append({"role": "tool", "content": "{}"})
    assert names == [
        "promql_query",
        "pg_activity",
        "pg_top_statements",
        "logql_query",
        "traceql_query",
        "get_runbook",
    ]
    slow = decide(
        [{"role": "user", "content": "PHASE=hypothesis\nAlert: DBSlowQueries\n\"id\": \"e1\"\n\"id\": \"e2\""}],
        None,
    )
    assert "orders_sku_created_idx" in slow["content"]
    assert "[e1]" in slow["content"]


def _wait_ready(name: str) -> None:
    deadline = time.time() + 240
    last = ""
    while time.time() < deadline:
        status = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}} {{.State.ExitCode}}", name],
            capture_output=True,
            text=True,
        )
        state = (status.stdout or "").strip()
        if state.startswith("exited"):
            logs = subprocess.run(["docker", "logs", "--tail", "80", name], capture_output=True, text=True)
            pytest.fail(f"postgres exited: {state}\n{logs.stdout}\n{logs.stderr}")
        check = subprocess.run(
            [
                "docker",
                "exec",
                name,
                "psql",
                "-U",
                "postgres",
                "-d",
                "shop",
                "-tAc",
                "SELECT count(*) FROM products",
            ],
            capture_output=True,
            text=True,
        )
        last = (check.stdout or "") + (check.stderr or "")
        logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
        ready_log = "ready for start up" in (logs.stdout + logs.stderr)
        if ready_log and check.returncode == 0 and check.stdout.strip() == "4":
            time.sleep(1)
            again = subprocess.run(
                [
                    "docker",
                    "exec",
                    name,
                    "psql",
                    "-U",
                    "postgres",
                    "-d",
                    "shop",
                    "-tAc",
                    "SELECT count(*) FROM products",
                ],
                capture_output=True,
                text=True,
            )
            if again.returncode == 0 and again.stdout.strip() == "4":
                return
        time.sleep(1)
    logs = subprocess.run(["docker", "logs", "--tail", "80", name], capture_output=True, text=True)
    pytest.fail(f"postgres did not become ready: {last}\n{logs.stdout}\n{logs.stderr}")


@pytest.fixture(scope="session")
def pg_dsns():
    if shutil.which("docker") is None:
        pytest.skip("docker not available")
    name = "agentic-sre-pg-test"
    subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)
    init = Path(__file__).resolve().parents[1] / "db" / "init"
    started = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-e",
            "POSTGRES_USER=postgres",
            "-e",
            "POSTGRES_PASSWORD=postgres",
            "-e",
            "POSTGRES_DB=shop",
            "-p",
            "55432:5432",
            "-v",
            f"{init}:/docker-entrypoint-initdb.d:ro",
            "postgres:16",
            "postgres",
            "-c",
            "shared_preload_libraries=pg_stat_statements",
            "-c",
            "pg_stat_statements.track=all",
            "-c",
            "track_io_timing=on",
            "-c",
            "max_connections=80",
            "-c",
            "fsync=off",
            "-c",
            "full_page_writes=off",
        ],
        capture_output=True,
        text=True,
    )
    if started.returncode != 0:
        pytest.skip(f"could not start postgres: {started.stderr}")
    try:
        _wait_ready(name)
        base = "127.0.0.1:55432/shop"
        yield {
            "app": f"postgresql://shop_app:shop_app@{base}",
            "ro": f"postgresql://sre_ro:sre_ro@{base}",
            "writer": f"postgresql://sre_writer:sre_writer@{base}",
        }
    finally:
        subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)


def test_live_postgres_tools(pg_dsns):
    os.environ["SLOW_PASSES"] = "1"
    os.environ["FAIL_LATENCY_SERIES"] = "20000"
    from agentic_sre.db import Database

    database = Database(pg_dsns["app"], application_name="checkout")
    try:
        products, elapsed = database.list_products(include_unpriced=False)
        assert elapsed >= 0
        assert {row["sku"] for row in products} == {"mug", "kettle"}
        assert all(row["price"] is not None for row in products)
        unpriced, _ = database.list_products(include_unpriced=True)
        assert any(row["price"] is None for row in unpriced)
        order = database.checkout("mug", 1, heavy=True)
        assert order["order_id"] > 0
        assert order["heavy_s"] > 0

        database.hold_lock()
        reader = PgClient(pg_dsns["ro"], pg_dsns["writer"])
        activity = _poll(lambda: reader.activity(), lambda body: body["waiting"] >= 1 and body["blocking_pids"])
        assert "Lock" in activity["summary"]
        assert "'locked-sku'" not in activity["summary"]
        holder = activity["blocking_pids"][0]
        with psycopg.connect(pg_dsns["ro"], row_factory=dict_row, autocommit=True) as conn:
            try:
                row = conn.execute("SELECT pg_terminate_backend(%s) AS ok", (holder,)).fetchone()
            except psycopg.Error:
                row = {"ok": False}
            assert row["ok"] is not True
        writer = PgClient(pg_dsns["ro"], pg_dsns["writer"])
        terminated = writer.terminate_backend(application_name="sre-lock")
        assert terminated["pids"]
        _poll(lambda: reader.activity(), lambda body: body["waiting"] == 0)
        database.release_lock()

        statements = reader.top_statements("total_exec_time")
        assert "orders" in statements["summary"].lower() or "SELECT" in statements["summary"]

        saturated = database.hold_connections()
        assert saturated["connections"] / saturated["max_connections"] >= 0.75
        released = database.release_connections()
        assert released["connections"] / released["max_connections"] < 0.75

        dropped = database.drop_orders_index()
        assert dropped["present"] is False
        slow = database.checkout("kettle", 1, heavy=False)
        assert slow["orders_by_sku_s"] >= 0
        created = writer.create_index(CREATE_INDEX_SQL)
        assert "orders_sku_created_idx" in created["summary"]
        assert database.index_present() is True
        with pytest.raises(ValueError):
            writer.create_index("DROP TABLE products")
    finally:
        database.close()


def _poll(fn, predicate, timeout: float = 15):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if predicate(last):
            return last
        time.sleep(0.3)
    raise AssertionError(last)
