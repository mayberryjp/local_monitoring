"""Report Docker images that are unused (no container references them) or dangling."""

from __future__ import annotations

from typing import Any

import docker
from docker.errors import DockerException

from local_monitoring.config import settings
from local_monitoring.domain.errors import CheckError


def _image_label(image: Any) -> str:
    """First repo tag, or the short image id for dangling/untagged images."""
    tags = image.tags
    return str(tags[0]) if tags else str(image.short_id)


def collect() -> dict[str, Any]:
    try:
        client = docker.DockerClient(base_url=settings.docker_host)
    except DockerException as exc:
        raise CheckError("docker_unreachable", "docker socket unavailable", str(exc)) from exc
    try:
        images = client.images.list()
        containers = client.containers.list(all=True)
    except DockerException as exc:
        raise CheckError("docker_unreachable", "docker socket request failed", str(exc)) from exc
    finally:
        client.close()

    in_use = {c.attrs.get("ImageID") for c in containers}
    # Unused = referenced by no container; dangling = untagged. Report the union.
    unused_images = [
        _image_label(img) for img in images if img.id not in in_use or not img.tags
    ]
    return {
        "unused": len(unused_images),
        "total": len(images),
        "unused_images": unused_images,
    }
