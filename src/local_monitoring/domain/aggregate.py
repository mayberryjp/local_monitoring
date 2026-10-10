"""Run all downstream checks in parallel and combine their reduced results."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType
from typing import Any

from local_monitoring.domain import (
    additional_monitors,
    allowlist,
    docker_containers,
    docker_images,
    docker_monitors,
    docker_updater,
    ping_monitors,
    portainer_stacks,
    status_page_monitors,
    uptime_kuma,
    webdav,
)
from local_monitoring.domain.errors import CheckError

Collector = Callable[[], dict[str, Any]]

# Each downstream reducer exposes a module-level ``collect()``. Resolving the
# attribute at call time keeps the set patchable and the modules decoupled.
CHECK_MODULES: dict[str, ModuleType] = {
    "uptime_kuma": uptime_kuma,
    "webdav": webdav,
    "docker_updater": docker_updater,
    "docker_containers": docker_containers,
    "docker_monitors": docker_monitors,
    "ping_monitors": ping_monitors,
    "additional_monitors": additional_monitors,
    "allowlist": allowlist,
    "docker_images": docker_images,
    "compose_stacks": portainer_stacks,
    "status_page_monitors": status_page_monitors,
}


def run_check(collector: Collector) -> dict[str, Any]:
    """Run one collector, converting a CheckError into an error envelope."""
    try:
        return {"status": "ok", **collector()}
    except CheckError as exc:
        result: dict[str, Any] = {"status": "error", "code": exc.code, "error": exc.message}
        if exc.detail is not None:
            result["detail"] = exc.detail
        return result


def collect_all(force_compose_refresh: bool = False) -> dict[str, Any]:
    """Invoke every check in parallel threads and return a keyed result object."""
    with ThreadPoolExecutor(max_workers=len(CHECK_MODULES)) as executor:
        futures = {}
        for name, module in CHECK_MODULES.items():
            collector = module.collect
            if name == "compose_stacks":
                collector = lambda module=module: module.collect(
                    force_refresh=force_compose_refresh
                )
            futures[name] = executor.submit(run_check, collector)
        return {name: future.result() for name, future in futures.items()}
