"""KubeSentra backend API.

Phase 4 scope: health/readiness, the Alertmanager webhook (POST /alerts)
with deduplication and background investigation, and incident queries.
The approval decision endpoint arrives in Phase 6/7.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from agent.observability import _enabled as _langfuse_enabled
from api.routes import decisions, incidents, webhook
from common.config import get_settings
from database import connection as db

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("kubesentra.api")

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("%s %s starting (env=%s)", settings.app_name, "0.4.0",
                settings.app_env)
    if _langfuse_enabled():
        logger.info("Langfuse tracing enabled")
    else:
        logger.info("Langfuse tracing disabled (no keys configured)")
    yield
    db.close_pool()


app = FastAPI(
    title=f"{settings.app_name} API",
    version="0.4.0",
    description="Kubernetes incident investigation and response agent.",
    lifespan=lifespan,
)
app.include_router(webhook.router)
app.include_router(incidents.router)
app.include_router(decisions.router)


@app.get("/health")
def health() -> dict:
    """Liveness probe: the process is up and serving requests."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready")
def ready() -> JSONResponse:
    """Readiness probe: dependencies (PostgreSQL) are actually reachable."""
    try:
        connected = db.check_connection()
    except Exception as exc:  # noqa: BLE001 - report any DB failure as 503
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "database": "unreachable",
                "error": type(exc).__name__,
            },
        )
    if not connected:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": "query_failed"},
        )
    return JSONResponse(
        status_code=200,
        content={"status": "ready", "database": "connected"},
    )
