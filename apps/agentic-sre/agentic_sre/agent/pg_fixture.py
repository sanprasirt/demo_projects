"""In-process Postgres stand-in so the mock path can run without a server."""

import threading


class FixtureState:
    def __init__(self):
        self._lock = threading.Lock()
        self.lock_waits = 0
        self.blocking_pid = 4242
        self.connection_ratio = 0.2
        self.connection_count = 12
        self.slow_seconds = 0.01
        self.terminated: list[str] = []
        self.cancelled: list[str] = []
        self.index_created = True

    def arm_lock(self) -> None:
        with self._lock:
            self.lock_waits = 2
            self.blocking_pid = 4242
            self.terminated = []

    def arm_connections(self) -> None:
        with self._lock:
            self.connection_ratio = 0.86
            self.connection_count = 69

    def arm_slow(self) -> None:
        with self._lock:
            self.slow_seconds = 0.42
            self.index_created = False

    def clear_lock(self, how: str) -> None:
        with self._lock:
            self.lock_waits = 0
            self.terminated.append(how)

    def clear_connections(self, how: str) -> None:
        with self._lock:
            self.connection_ratio = 0.2
            self.connection_count = 12
            self.terminated.append(how)

    def mark_index(self) -> None:
        with self._lock:
            self.index_created = True
            self.slow_seconds = 0.01

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "lock_waits": self.lock_waits,
                "blocking_pid": self.blocking_pid,
                "connection_ratio": self.connection_ratio,
                "connection_count": self.connection_count,
                "slow_seconds": self.slow_seconds,
                "terminated": list(self.terminated),
                "cancelled": list(self.cancelled),
                "index_created": self.index_created,
            }


STATE = FixtureState()
