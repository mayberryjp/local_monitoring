"""Remediation action endpoints triggered from the dashboard."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from bottle import Bottle, request, response

from local_monitoring.domain import (
    additional_monitors,
    docker_containers,
    docker_images,
    docker_monitors,
    docker_updater,
    ping_monitors,
    portainer_stacks,
    uptime_kuma_v2,
)
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


def _target(field: str) -> str:
    """Read a per-item action's JSON body field (missing/blank -> empty string)."""
    try:
        body = request.json or {}
    except (ValueError, TypeError):
        body = {}
    value = body.get(field) if isinstance(body, dict) else None
    return str(value).strip() if value else ""


def _missing(field: str) -> dict[str, Any]:
    response.status = 400
    return {"status": "error", "code": "invalid_request", "error": f"missing {field!r} in body"}


def register_action_routes(app: Bottle) -> None:
    @app.post("/actions/update-all")
    def update_all() -> dict[str, Any]:
        return _run(docker_updater.update_all)

    @app.post("/actions/update")
    def update_one() -> dict[str, Any]:
        name = _target("name")
        return _missing("name") if not name else _run(lambda: docker_updater.update_one(name))

    @app.post("/actions/prune-images")
    def prune_images() -> dict[str, Any]:
        return _run(docker_images.prune_unused)

    @app.post("/actions/delete-image")
    def delete_image() -> dict[str, Any]:
        image = _target("image")
        return _missing("image") if not image else _run(lambda: docker_images.remove_image(image))

    @app.post("/actions/add-ping-monitor")
    def add_ping_monitor() -> dict[str, Any]:
        device = _target("device")
        if not device:
            return _missing("device")
        return _run(lambda: ping_monitors.add_ping_monitor(device))

    @app.post("/actions/add-docker-monitor")
    def add_docker_monitor() -> dict[str, Any]:
        container = _target("container")
        host_id = _target("host_id")
        if not container:
            return _missing("container")
        if not host_id:
            return _missing("host_id")
        try:
            parsed_host_id = int(host_id)
        except ValueError:
            response.status = 400
            return {"status": "error", "code": "invalid_request", "error": "host_id must be an integer"}
        return _run(lambda: docker_monitors.add_docker_monitor(container, parsed_host_id))

    @app.post("/actions/clear-heartbeats")
    def clear_heartbeats() -> dict[str, Any]:
        return _run(uptime_kuma_v2.clear_all_heartbeats)

    @app.post("/actions/redeploy-compose")
    def redeploy_compose() -> dict[str, Any]:
        container = _target("container")
        if not container:
            return _missing("container")
        return _run(lambda: portainer_stacks.redeploy_for_container(container))

    @app.post("/actions/delete-monitor")
    def delete_monitor() -> dict[str, Any]:
        name = _target("name")
        if not name:
            return _missing("name")
        return _run(lambda: additional_monitors.delete_monitor(name))

    @app.post("/actions/start-container")
    def start_container() -> dict[str, Any]:
        name = _target("name")
        if not name:
            return _missing("name")
        return _run(lambda: docker_containers.start_container(name))

    @app.post("/actions/delete-container")
    def delete_container() -> dict[str, Any]:
        name = _target("name")
        if not name:
            return _missing("name")
        return _run(lambda: docker_containers.remove_container(name))
