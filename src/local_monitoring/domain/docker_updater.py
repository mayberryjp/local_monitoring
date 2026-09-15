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
