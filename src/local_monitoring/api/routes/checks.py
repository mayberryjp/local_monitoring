"""Aggregate and individual downstream check endpoints."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from bottle import Bottle, request, response

from local_monitoring.domain import (
    additional_monitors,
    allowlist,
    docker_containers,
    docker_images,
    docker_monitors,
    docker_updater,
    ping_monitors,
    portainer_stacks,
    uptime_kuma,
    uptime_kuma_v2,
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

    @app.get("/docker-monitors")
    def docker_monitors_check() -> dict[str, Any]:
        return _run(docker_monitors.collect)

    @app.get("/docker-hosts")
    def docker_hosts() -> dict[str, Any]:
        def collect_hosts() -> dict[str, Any]:
            hosts = uptime_kuma_v2.fetch_docker_hosts()
            return {"hosts": hosts, "count": len(hosts)}

        return _run(collect_hosts)

    @app.get("/compose-stacks")
    def compose_stacks() -> dict[str, Any]:
        force_refresh = request.query.get("refresh", "").lower() in {"1", "true", "yes"}
        return _run(lambda: portainer_stacks.collect(force_refresh=force_refresh))

    @app.get("/ping-monitors")
    def ping_monitors_check() -> dict[str, Any]:
        return _run(ping_monitors.collect)

    @app.get("/additional-monitors")
    def additional_monitors_check() -> dict[str, Any]:
        return _run(additional_monitors.collect)

    @app.get("/allowlist")
    def allowlist_check() -> dict[str, Any]:
        return _run(allowlist.collect)

    @app.get("/docker-images")
    def docker_images_check() -> dict[str, Any]:
        return _run(docker_images.collect)
