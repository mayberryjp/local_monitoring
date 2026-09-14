"""Aggregate and individual downstream check endpoints."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from bottle import Bottle, response

from local_monitoring.domain import (
    docker_containers,
    docker_updater,
    uptime_kuma,
    webdav,
)
from local_monitoring.domain.aggregate import collect_all
from local_monitoring.domain.errors import CheckError

Collector = Callable[[], dict[str, Any]]


def _run(collector: Collector) -> dict[str, Any]:
    try:
        return {"status": "ok", **collector()}
    except CheckError as exc:
        response.status = 503
        result: dict[str, Any] = {"status": "error", "code": exc.code, "error": exc.message}
        if exc.detail is not None:
            result["detail"] = exc.detail
        return result


def register_check_routes(app: Bottle) -> None:
    @app.get("/summary")
    def summary() -> dict[str, Any]:
        return {"status": "ok", "checks": collect_all()}

    @app.get("/uptime-kuma")
    def uptime_kuma_check() -> dict[str, Any]:
        return _run(uptime_kuma.collect)

    @app.get("/webdav")
    def webdav_check() -> dict[str, Any]:
        return _run(webdav.collect)

    @app.get("/docker-updater")
    def docker_updater_check() -> dict[str, Any]:
        return _run(docker_updater.collect)

    @app.get("/docker")
    def docker_check() -> dict[str, Any]:
        return _run(docker_containers.collect)
