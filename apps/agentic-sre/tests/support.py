import socket
import threading
import time

import httpx
import uvicorn


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class Running:
    def __init__(self, app, port: int):
        self.port = port
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self, timeout: float = 20) -> "Running":
        self.thread.start()
        deadline = time.time() + timeout
        last = ""
        while time.time() < deadline:
            try:
                response = httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=0.5)
                if response.status_code == 200:
                    return self
                last = response.text
            except httpx.HTTPError as exc:
                last = str(exc)
            time.sleep(0.1)
        raise RuntimeError(f"server {self.port} did not start: {last}")

    def stop(self) -> None:
        self.server.should_exit = True


def wait_until(predicate, timeout: float = 45, interval: float = 0.2):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"timed out; last={last!r}")
