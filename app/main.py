from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import REPO_ROOT
from .db import init_db
from .routes import api, auth_routes, ui

app = FastAPI(title="Car Tracker", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(REPO_ROOT / "app" / "static")), name="static")
app.include_router(auth_routes.router)
app.include_router(ui.router)
app.include_router(api.router)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    