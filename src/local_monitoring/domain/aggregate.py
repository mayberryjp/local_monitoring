"""Run all downstream checks in parallel and combine their reduced results."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType
from typing import Any

from local_monitoring.domain import (
    docker_containers,
    docker_updater,
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


def collect_all() -> dict[str, Any]:
    """Invoke every check in parallel threads and return a keyed result object."""
    with ThreadPoolExecutor(max_workers=len(CHECK_MODULES)) as executor:
        futures = {
            name: executor.submit(run_check, module.collect)
            for name, module in CHECK_MODULES.items()
        }
        return {name: future.result() for name, future in futures.items()}
