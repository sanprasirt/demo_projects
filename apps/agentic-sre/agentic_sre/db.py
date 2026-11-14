"""psycopg pool and the shop queries catalog and checkout actually run."""

import logging
import os
import threading
import time

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout

log = logging.getLogger("agentic_sre.db")

FAST_ORDERS_SQL = """
SELECT /* orders_by_sku */ count(*)::bigint AS n
FROM orders
WHERE sku = %s
"""

# One statement. generate_series multiplies the seq scan only when the index is gone.
SLOW_ORDERS_SQL = """
SELECT /* orders_by_sku */ count(md5(o.note || g.n::text))::bigint AS n
FROM orders AS o
CROSS JOIN generate_series(1, %s) AS g(n)
WHERE o.sku = %s
"""

INDEX_NAME = "orders_sku_created_idx"
CREATE_INDEX_SQL = (
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS orders_sku_created_idx "
    "ON orders (sku, created_at DESC)"
)
LOCK_SKU = "locked-sku"


def slow_passes() -> int:
    raw = os.environ.get("SLOW_PASSES", "4")
    try:
        return max(1, int(raw))
    except ValueError:
        return 4


def latency_series() -> int:
    raw = os.environ.get("FAIL_LATENCY_SERIES", "2000000")
    try:
        return max(1, int(raw))
    except ValueError:
        return 2_000_000


class Database:
    def __init__(self, dsn: str, *, application_name: str):
        self.dsn = dsn
        self.application_name = application_name
        self.pool = ConnectionPool(
            dsn,
            min_size=1,
            max_size=4,
            timeout=2,
            open=True,
            kwargs={
                "connect_timeout": 5,
                "application_name": application_name,
                "row_factory": dict_row,
                "options": "-c statement_timeout=8000",
            },
            name=application_name,
        )
        self._lock_stop = threading.Event()
        self._conn_stop = threading.Event()
        self._lock_thread: threading.Thread | None = None
        self._probe_thread: threading.Thread | None = None
        self._conn_thread: threading.Thread | None = None
        self._guard = threading.Lock()

    def close(self) -> None:
        self.release_lock()
        self.release_connections()
        self.pool.close()

    def list_products(self, *, include_unpriced: bool) -> tuple[list[dict], float]:
        started = time.perf_counter()
        with self.pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT sku, name, price
                FROM products
                WHERE category <> 'internal'
                  AND (%s OR price IS NOT NULL)
                ORDER BY sku
                """,
                (include_unpriced,),
            ).fetchall()
            conn.commit()
        products = [
            {
                "sku": row["sku"],
                "name": row["name"],
                "price": None if row["price"] is None else float(row["price"]),
            }
            for row in rows
        ]
        return products, time.perf_counter() - started

    def checkout(self, sku: str, qty: int, *, heavy: bool) -> dict:
        started = time.perf_counter()
        heavy_s = 0.0
        orders_s = 0.0
        with self.pool.connection() as conn:
            if heavy:
                burn_started = time.perf_counter()
                conn.execute(
                    "SELECT count(*)::bigint FROM generate_series(1, %s) AS g WHERE md5(g::text) ~ '^0'",
                    (latency_series(),),
                )
                conn.commit()
                heavy_s = time.perf_counter() - burn_started
            with conn.transaction():
                exists = conn.execute("SELECT 1 FROM products WHERE sku = %s AND price IS NOT NULL", (sku,)).fetchone()
                if exists is None:
                    raise LookupError(sku)
                conn.execute(
                    "UPDATE products SET stock = GREATEST(stock - %s, 0) WHERE sku = %s",
                    (qty, sku),
                )
                inserted = conn.execute(
                    "INSERT INTO orders (sku, qty, note) VALUES (%s, %s, %s) RETURNING id",
                    (sku, qty, "checkout"),
                ).fetchone()
                sku_started = time.perf_counter()
                counted = self._orders_by_sku(conn, sku)
                orders_s = time.perf_counter() - sku_started
        return {
            "order_id": int(inserted["id"]),
            "counted": int(counted),
            "latency_s": time.perf_counter() - started,
            "heavy_s": heavy_s,
            "orders_by_sku_s": orders_s,
        }

    def _orders_by_sku(self, conn, sku: str) -> int:
        if self._index_present(conn):
            row = conn.execute(FAST_ORDERS_SQL, (sku,)).fetchone()
        else:
            row = conn.execute(SLOW_ORDERS_SQL, (slow_passes(), sku)).fetchone()
            log.warning(
                "orders_by_sku sequential scan sku_param_masked passes=%s",
                slow_passes(),
            )
        return int(row["n"])

    def _index_present(self, conn) -> bool:
        row = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = %s) AS present",
            (INDEX_NAME,),
        ).fetchone()
        return bool(row["present"])

    def index_present(self) -> bool:
        with self._direct(application_name=f"{self.application_name}-admin") as conn:
            return self._index_present(conn)

    def drop_orders_index(self) -> dict:
        with self._direct(application_name=f"{self.application_name}-ddl", autocommit=True) as conn:
            conn.execute("SET lock_timeout = '15s'")
            conn.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
        log.warning("dropped %s", INDEX_NAME)
        return {"ok": True, "index": INDEX_NAME, "present": self.index_present()}

    def create_orders_index(self) -> dict:
        with self._direct(application_name=f"{self.application_name}-ddl", autocommit=True) as conn:
            conn.execute("SET lock_timeout = '20s'")
            conn.execute(CREATE_INDEX_SQL)
            _reset_statements(conn)
        log.warning("created %s", INDEX_NAME)
        return {"ok": True, "index": INDEX_NAME, "present": self.index_present()}

    def hold_lock(self) -> dict:
        with self._guard:
            if self._lock_thread and self._lock_thread.is_alive():
                return self.status()
            self._lock_stop = threading.Event()
            acquired = threading.Event()
            self._lock_ok = False
            self._lock_thread = threading.Thread(
                target=self._lock_runner,
                args=(acquired,),
                name="sre-lock",
                daemon=True,
            )
            self._lock_thread.start()
        if not acquired.wait(timeout=10) or not self._lock_ok:
            raise RuntimeError("lock holder did not acquire the row")
        self._probe_thread = threading.Thread(target=self._probe_runner, name="sre-lock-wait", daemon=True)
        self._probe_thread.start()
        time.sleep(0.4)
        log.warning("orders-db lock wait holder=sre-lock target=%s", LOCK_SKU)
        return self.status()

    def release_lock(self) -> dict:
        self._lock_stop.set()
        for thread in (self._lock_thread, self._probe_thread):
            if thread and thread.is_alive():
                thread.join(timeout=8)
        return self.status()

    def hold_connections(self) -> dict:
        with self._guard:
            if self._conn_thread and self._conn_thread.is_alive():
                return self.status()
            self._conn_stop = threading.Event()
            ready = threading.Event()
            self._conn_thread = threading.Thread(
                target=self._connection_runner,
                args=(ready,),
                name="sre-hold",
                daemon=True,
            )
            self._conn_thread.start()
        if not ready.wait(timeout=20):
            raise RuntimeError("connection holder did not reach the target")
        status = self.status()
        ratio = status["connections"] / max(status["max_connections"], 1)
        if ratio < 0.75:
            raise RuntimeError(f"connections are at {ratio:.0%} of max_connections")
        log.warning("orders-db connection pool exhausted by sre-hold sessions")
        return status

    def release_connections(self) -> dict:
        self._conn_stop.set()
        if self._conn_thread and self._conn_thread.is_alive():
            self._conn_thread.join(timeout=8)
        return self.status()

    def status(self) -> dict:
        with self._direct(application_name=f"{self.application_name}-admin") as conn:
            sessions = conn.execute(
                """
                SELECT application_name, state, wait_event_type, count(*)::int AS n
                FROM pg_stat_activity
                WHERE application_name LIKE 'sre-%%'
                GROUP BY 1, 2, 3
                ORDER BY 1
                """
            ).fetchall()
            totals = conn.execute(
                """
                SELECT
                  count(*)::int AS connections,
                  current_setting('max_connections')::int AS max_connections
                FROM pg_stat_activity
                """
            ).fetchone()
            present = self._index_present(conn)
        return {
            "ok": True,
            "index_present": present,
            "sessions": [dict(row) for row in sessions],
            "connections": totals["connections"],
            "max_connections": totals["max_connections"],
            "lock_thread": bool(self._lock_thread and self._lock_thread.is_alive()),
            "connection_thread": bool(self._conn_thread and self._conn_thread.is_alive()),
        }

    def _lock_runner(self, acquired: threading.Event) -> None:
        conn = None
        try:
            conn = self._connect(application_name="sre-lock")
            conn.execute("BEGIN")
            conn.execute("SELECT stock FROM products WHERE sku = %s FOR UPDATE", (LOCK_SKU,))
            self._lock_ok = True
            acquired.set()
            while not self._lock_stop.is_set():
                time.sleep(0.4)
                conn.execute("SELECT 1")
            conn.rollback()
        except Exception:
            log.info("lock holder ended", exc_info=True)
            acquired.set()
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _probe_runner(self) -> None:
        while not self._lock_stop.is_set():
            conn = None
            try:
                conn = self._connect(application_name="sre-lock-wait")
                conn.execute("BEGIN")
                conn.execute("SELECT stock FROM products WHERE sku = %s FOR UPDATE", (LOCK_SKU,))
                conn.rollback()
                return
            except Exception:
                log.info("lock probe ended", exc_info=True)
                if self._lock_stop.is_set():
                    return
                time.sleep(0.3)
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

    def _connection_runner(self, ready: threading.Event) -> None:
        extra: list[psycopg.Connection] = []
        pooled = []
        try:
            while len(pooled) < (self.pool.max_size or 4) and not self._conn_stop.is_set():
                try:
                    pooled.append(self.pool.getconn(timeout=2))
                except PoolTimeout:
                    break
            with self._direct(application_name="sre-hold-admin") as conn:
                limits = conn.execute(
                    """
                    SELECT count(*)::int AS connections,
                           current_setting('max_connections')::int AS max_connections
                    FROM pg_stat_activity
                    """
                ).fetchone()
            target = int(limits["max_connections"] * 0.82)
            while not self._conn_stop.is_set():
                with self._direct(application_name="sre-hold-admin") as conn:
                    current = conn.execute("SELECT count(*)::int AS n FROM pg_stat_activity").fetchone()["n"]
                    limit = conn.execute("SELECT current_setting('max_connections')::int AS n").fetchone()["n"]
                if current >= target or limit - current <= 8:
                    ready.set()
                    break
                held = None
                try:
                    held = self._connect(application_name="sre-hold", autocommit=True)
                    held.execute("SELECT 1")
                    extra.append(held)
                except psycopg.OperationalError:
                    log.warning("stopped opening sre-hold sessions", exc_info=True)
                    if held is not None:
                        try:
                            held.close()
                        except Exception:
                            pass
                    ready.set()
                    break
            else:
                ready.set()
            while not self._conn_stop.is_set():
                time.sleep(0.8)
                alive = []
                for conn in extra:
                    try:
                        conn.execute("SELECT 1")
                        alive.append(conn)
                    except Exception:
                        try:
                            conn.close()
                        except Exception:
                            pass
                extra = alive
                if not extra:
                    break
        finally:
            ready.set()
            self._conn_stop.set()
            for conn in extra:
                try:
                    conn.close()
                except Exception:
                    pass
            for conn in pooled:
                try:
                    self.pool.putconn(conn)
                except Exception:
                    pass

    def _connect(self, *, application_name: str, autocommit: bool = False) -> psycopg.Connection:
        return psycopg.connect(
            self.dsn,
            autocommit=autocommit,
            connect_timeout=5,
            application_name=application_name,
            row_factory=dict_row,
        )

    def _direct(self, *, application_name: str, autocommit: bool = True):
        return psycopg.connect(
            self.dsn,
            autocommit=autocommit,
            connect_timeout=5,
            application_name=application_name,
            row_factory=dict_row,
        )


def _reset_statements(conn) -> None:
    try:
        conn.execute("SELECT pg_stat_statements_reset()")
    except psycopg.Error:
        log.warning("pg_stat_statements_reset failed", exc_info=True)
