import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles

from .config import REPO_ROOT
from .db import init_db
from .routes import api, auth_routes, ui


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Car Tracker",
    version="0.1.0",
    lifespan=lifespan,
    description=(
        "JSON API for the Car Tracker app. Lets a caller list buildings and "
        "spaces, manage cars (create, move, archive), and create or cancel "
        "bookings that reserve a space for a car for a time window."
    ),
)
app.mount("/static", StaticFiles(directory=str(REPO_ROOT / "app" / "static")), name="static")
app.include_router(auth_routes.router)
app.include_router(ui.router)
app.include_router(api.router)


def _public_openapi() -> dict:
    if app.openapi_schema is not None:
        return app.openapi_schema

    public_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    servers = [{"url": public_url}] if public_url else None

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        servers=servers,
    )

    schema["paths"] = {
        path: ops for path, ops in schema["paths"].items() if path.startswith("/api/")
    }

    referenced: set[str] = set()
    for ops in schema["paths"].values():
        for op in ops.values():
            if isinstance(op, dict):
                referenced.update(_collect_refs(op))
    components = schema.get("components", {}).get("schemas", {})
    if components:
        kept = _expand_refs(referenced, components)
        schema["components"]["schemas"] = {k: v for k, v in components.items() if k in kept}

    app.openapi_schema = schema
    return schema


def _collect_refs(node) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[-1])
        for v in node.values():
            found |= _collect_refs(v)
    elif isinstance(node, list):
        for v in node:
            found |= _collect_refs(v)
    return found


def _expand_refs(seed: set[str], components: dict) -> set[str]:
    kept = set(seed)
    frontier = set(seed)
    while frontier:
        nxt: set[str] = set()
        for name in frontier:
            schema = components.get(name)
            if schema is None:
                continue
            for ref in _collect_refs(schema):
                if ref not in kept:
                    kept.add(ref)
                    nxt.add(ref)
        frontier = nxt
    return kept


app.openapi = _public_openapi