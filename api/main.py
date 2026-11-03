"""KubeSentra backend API.

Phase 1 scope: liveness and readiness endpoints only. The Alertmanager
webhook, incident endpoints and the approval decision endpoint are added in
later phases - nothing here pretends they exist yet.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from common.config import get_settings
from database import connection as db

settings = get_settings()

app = FastAPI(
    title=f"{settings.app_name} API",
    version="0.1.0",
    description="Kubernetes incident investigation and response agent "
                "(Phase 1: foundation).",
)


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
