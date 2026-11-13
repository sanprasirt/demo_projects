import threading
import time


class FailState:
    MODES = {"off", "error", "leak", "latency"}

    def __init__(self):
        self.mode = "off"
        self.note = ""
        self.leak = bytearray()
        self.leak_bytes = 0
        self._lock = threading.Lock()

    def set(self, mode: str, note: str = "") -> None:
        if mode not in self.MODES:
            raise ValueError(mode)
        with self._lock:
            self.mode = mode
            self.note = note
            if mode == "off":
                self.leak = bytearray()
                self.leak_bytes = 0

    def snapshot(self) -> dict:
        with self._lock:
            return {"mode": self.mode, "note": self.note, "leak_bytes": self.leak_bytes}

    def grow_leak(self) -> int:
        with self._lock:
            if self.mode != "leak":
                return self.leak_bytes
            self.leak_bytes = min(self.leak_bytes + 5_000_000, 200_000_000)
            if len(self.leak) < 2_000_000:
                self.leak.extend(b"x" * 100_000)
            return self.leak_bytes

    def delay(self, *, base_s: float, slow_s: float) -> float:
        with self._lock:
            mode = self.mode
        if mode == "latency":
            time.sleep(slow_s)
            return slow_s
        if base_s > 0:
            time.sleep(base_s)
        return base_s
