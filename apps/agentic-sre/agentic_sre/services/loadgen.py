import logging
import os
import random
import threading
import time

import httpx
import uvicorn
from fastapi import FastAPI

log = logging.getLogger("loadgen")


def create_app() -> FastAPI:
    app = FastAPI(title="loadgen")

    @app.get("/health")
    def health():
        return {"ok": True, "service": "loadgen"}

    return app


def _loop(gateway: str, interval: float) -> None:
    client = httpx.Client(timeout=5.0, trust_env=False)
    while True:
        try:
            if random.random() < 0.75:
                client.get(gateway.rstrip("/") + "/api/products")
            else:
                client.post(gateway.rstrip("/") + "/api/checkout", json={"sku": "mug", "qty": 1})
        except Exception as exc:
            log.info("request failed: %s", exc)
        time.sleep(interval)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    gateway = os.environ.get("GATEWAY_URL", "http://gateway:8000")
    interval = float(os.environ.get("LOAD_INTERVAL_S", "0.2"))
    threading.Thread(target=_loop, args=(gateway, interval), name="load", daemon=True).start()
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
