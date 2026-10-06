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


def _human_size(num: float) -> str:
    size = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def _unused_image_labels(client: Any) -> list[str]:
    """Labels of images referenced by no container (union with dangling/untagged)."""
    images = client.images.list()
    containers = client.containers.list(all=True)
    # containers.list() returns inspect-shaped attrs (image id under "Image");
    # the lighter list-endpoint shape uses "ImageID" instead.
    in_use = {c.attrs.get("ImageID") or c.attrs.get("Image") for c in containers}
    # Unused = referenced by no container; dangling = untagged. Report the union.
    return [_image_label(img) for img in images if img.id not in in_use or not img.tags]


def collect() -> dict[str, Any]:
    try:
        client = docker.DockerClient(base_url=settings.docker_host)
    except DockerException as exc:
        raise CheckError("docker_unreachable", "docker socket unavailable", str(exc)) from exc
    try:
        total = len(client.images.list())
        unused_images = _unused_image_labels(client)
    except DockerException as exc:
        raise CheckError("docker_unreachable", "docker socket request failed", str(exc)) from exc
    finally:
        client.close()

    return {
        "unused": len(unused_images),
        "total": total,
        "unused_images": unused_images,
    }


def remove_image(reference: str) -> dict[str, Any]:
    """Remove a single image that is currently unused (by tag or short id).

    The reference is validated against the live unused set before removal, so a caller
    cannot delete an in-use image, and Docker is called with ``force=False`` as a second
    guard (it refuses to remove an image a container depends on).
    """
    target = reference.strip()
    try:
        client = docker.DockerClient(base_url=settings.docker_host)
    except DockerException as exc:
        raise CheckError("docker_unreachable", "docker socket unavailable", str(exc)) from exc
    try:
        if target not in _unused_image_labels(client):
            raise CheckError("not_found", f"image {reference!r} is not in the unused set")
        client.images.remove(image=target, force=False)
    except DockerException as exc:
        raise CheckError("docker_unreachable", "docker image remove failed", str(exc)) from exc
    finally:
        client.close()

    return {"removed": target}


def prune_unused() -> dict[str, Any]:
    """Remove every image not referenced by a container (Docker's ``prune -a``).

    Uses Docker's own prune semantics (``dangling=False`` = all unused), so an image
    still in use by any container is never removed — the operation can't break a
    running service. Requires write access to the Docker socket.
    """
    try:
        client = docker.DockerClient(base_url=settings.docker_host)
    except DockerException as exc:
        raise CheckError("docker_unreachable", "docker socket unavailable", str(exc)) from exc
    try:
        result = client.images.prune(filters={"dangling": False})
    except DockerException as exc:
        raise CheckError("docker_unreachable", "docker image prune failed", str(exc)) from exc
    finally:
        client.close()

    reclaimed = int(result.get("SpaceReclaimed") or 0)
    deleted = sum(1 for entry in (result.get("ImagesDeleted") or []) if entry.get("Deleted"))
    return {
        "deleted": deleted,
        "space_reclaimed": reclaimed,
        "space_reclaimed_human": _human_size(reclaimed),
    }
