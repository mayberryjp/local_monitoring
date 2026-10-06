"""Remediation action endpoints triggered from the dashboard."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from bottle import Bottle, response

from local_monitoring.domain import docker_images, docker_updater
from local_monitoring.domain.errors import CheckError

Action = Callable[[], dict[str, Any]]


def _run(action: Action) -> dict[str, Any]:
    try:
        return {"status": "ok", **action()}
    except CheckError as exc:
        response.status = 503
        result: dict[str, Any] = {"status": "error", "code": exc.code, "error": exc.message}
        if exc.detail is not None:
            result["detail"] = exc.detail
        return result


def register_action_routes(app: Bottle) -> None:
    @app.post("/actions/update-all")
    def update_all() -> dict[str, Any]:
        return _run(docker_updater.update_all)

    @app.post("/actions/prune-images")
    def prune_images() -> dict[str, Any]:
        return _run(docker_images.prune_unused)
