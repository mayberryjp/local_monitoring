"""Health and readiness endpoints."""

from __future__ import annotations

from typing import Any

from bottle import Bottle

SERVICE_NAME = "local-monitoring-api"


def register_health_routes(app: Bottle) -> None:
    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": SERVICE_NAME}

    @app.get("/ready")
    def ready() -> dict[str, Any]:
        # The service has no hard startup dependency: downstream reachability is
        # evaluated per-request and reported inside each check's response.
        return {"status": "ok"}
