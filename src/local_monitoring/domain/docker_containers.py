"""Count running and stopped containers via the Docker socket."""

from __future__ import annotations

from typing import Any

import docker
from docker.errors import DockerException

from local_monitoring.config import settings
from local_monitoring.domain.errors import CheckError


def collect() -> dict[str, Any]:
    try:
        client = docker.DockerClient(base_url=settings.docker_host)
    except DockerException as exc:
        raise CheckError("docker_unreachable", "docker socket unavailable", str(exc)) from exc
    try:
        containers = client.containers.list(all=True)
    except DockerException as exc:
        raise CheckError("docker_unreachable", "docker socket request failed", str(exc)) from exc
    finally:
        client.close()

    running = sum(1 for c in containers if c.status == "running")
    total = len(containers)
    stopped_containers = [c.name for c in containers if c.status != "running"]
    return {
        "running": running,
        "stopped": total - running,
        "total": total,
        "stopped_containers": stopped_containers,
    }


def _open_client() -> Any:
    try:
        return docker.DockerClient(base_url=settings.docker_host)
    except DockerException as exc:
        raise CheckError("docker_unreachable", "docker socket unavailable", str(exc)) from exc


def _find_stopped(client: Any, name: str) -> Any:
    """The container object for a currently-stopped container of that name, else None."""
    try:
        containers = client.containers.list(all=True)
    except DockerException as exc:
        raise CheckError("docker_unreachable", "docker socket request failed", str(exc)) from exc
    return next((c for c in containers if c.name == name and c.status != "running"), None)


def start_container(name: str) -> dict[str, Any]:
    """Start a stopped container; the name is validated against the live stopped set."""
    target = name.strip()
    client = _open_client()
    try:
        container = _find_stopped(client, target)
        if container is None:
            raise CheckError("not_found", f"container {name!r} is not a stopped container")
        container.start()
    except DockerException as exc:
        raise CheckError("docker_unreachable", "docker container start failed", str(exc)) from exc
    finally:
        client.close()
    return {"started": target}


def remove_container(name: str) -> dict[str, Any]:
    """Delete a stopped container; the name is validated against the live stopped set."""
    target = name.strip()
    client = _open_client()
    try:
        container = _find_stopped(client, target)
        if container is None:
            raise CheckError("not_found", f"container {name!r} is not a stopped container")
        container.remove(force=False)
    except DockerException as exc:
        raise CheckError("docker_unreachable", "docker container remove failed", str(exc)) from exc
    finally:
        client.close()
    return {"deleted": target}
