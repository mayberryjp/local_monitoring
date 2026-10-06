"""Reduce docker-updater's status to a pending-updates count."""

from __future__ import annotations

from typing import Any

import requests

from local_monitoring.config import settings
from local_monitoring.domain.errors import CheckError


def collect() -> dict[str, Any]:
    if not settings.docker_updater_base_url:
        raise CheckError("not_configured", "docker-updater is not configured")

    url = f"{settings.docker_updater_base_url.rstrip('/')}/api/status"
    try:
        resp = requests.get(url, timeout=settings.http_timeout_seconds)
    except requests.RequestException as exc:
        raise CheckError("upstream_unreachable", "docker-updater request failed", str(exc)) from exc
    if resp.status_code != 200:
        raise CheckError("upstream_error", f"docker-updater returned HTTP {resp.status_code}")

    containers = resp.json().get("containers") or []
    pending_images = [c.get("image") for c in containers if c.get("status") == "update"]
    return {"pending_updates": len(pending_images), "pending_images": pending_images}


def _pending_container_names() -> list[str]:
    """Container names docker-updater currently reports as having an update."""
    url = f"{settings.docker_updater_base_url.rstrip('/')}/api/status"
    try:
        resp = requests.get(url, timeout=settings.http_timeout_seconds)
    except requests.RequestException as exc:
        raise CheckError("upstream_unreachable", "docker-updater request failed", str(exc)) from exc
    if resp.status_code != 200:
        raise CheckError("upstream_error", f"docker-updater returned HTTP {resp.status_code}")
    containers = resp.json().get("containers") or []
    return [c["name"] for c in containers if c.get("status") == "update" and c.get("name")]


def update_all() -> dict[str, Any]:
    """Trigger a docker-updater update for every container with a pending update.

    docker-updater has no bulk endpoint, so this fans out one POST /api/update/<name>
    per pending container. A 409 means that container is already updating, which for a
    "update everything" action is the desired end state, so it counts as triggered.
    """
    if not settings.docker_updater_base_url:
        raise CheckError("not_configured", "docker-updater is not configured")

    base = settings.docker_updater_base_url.rstrip("/")
    triggered: list[str] = []
    for name in _pending_container_names():
        try:
            resp = requests.post(
                f"{base}/api/update/{name}", timeout=settings.http_timeout_seconds
            )
        except requests.RequestException as exc:
            raise CheckError(
                "upstream_unreachable", "docker-updater update request failed", str(exc)
            ) from exc
        if resp.status_code not in (200, 409):
            raise CheckError(
                "upstream_error",
                f"docker-updater update of {name} returned HTTP {resp.status_code}",
            )
        triggered.append(name)
    return {"triggered": triggered, "count": len(triggered)}
