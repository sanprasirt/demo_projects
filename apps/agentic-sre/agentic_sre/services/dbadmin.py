"""Admin routes that inject and clear the database scenarios."""

from fastapi import FastAPI, HTTPException, Request


def mount_db_admin(app: FastAPI, admin_token: str) -> None:
    def _db():
        database = getattr(app.state, "db", None)
        if database is None:
            raise HTTPException(status_code=503, detail="DATABASE_URL is not set")
        return database

    def _authorized(request: Request) -> None:
        if request.headers.get("x-admin-token") != admin_token:
            raise HTTPException(status_code=401, detail="admin token required")

    @app.get("/admin/db")
    def get_db(request: Request):
        _authorized(request)
        return _db().status()

    @app.post("/admin/db/{name}")
    async def post_db(name: str, request: Request):
        _authorized(request)
        body = await request.json()
        action = body.get("action", "")
        database = _db()
        try:
            if name == "lock" and action == "hold":
                return database.hold_lock()
            if name == "lock" and action == "release":
                return database.release_lock()
            if name == "connections" and action == "hold":
                return database.hold_connections()
            if name == "connections" and action == "release":
                return database.release_connections()
            if name == "index" and action == "drop":
                return database.drop_orders_index()
            if name == "index" and action == "create":
                return database.create_orders_index()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail="unknown database action")
