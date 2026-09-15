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
