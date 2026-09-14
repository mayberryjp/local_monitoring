"""Reduce an Uptime Kuma status page to a simple up/down counter."""

from __future__ import annotations

from typing import Any

import requests

from local_monitoring.config import settings
from local_monitoring.domain.errors import CheckError


def collect() -> dict[str, Any]:
    if not settings.uptime_kuma_base_url or not settings.uptime_kuma_slug:
        raise CheckError("not_configured", "uptime-kuma is not configured")

    url = (
        f"{settings.uptime_kuma_base_url.rstrip('/')}"
        f"/api/status-page/heartbeat/{settings.uptime_kuma_slug}"
    )
    try:
        resp = requests.get(url, timeout=settings.http_timeout_seconds)
    except requests.RequestException as exc:
        raise CheckError("upstream_unreachable", "uptime-kuma request failed", str(exc)) from exc
    if resp.status_code != 200:
        raise CheckError("upstream_error", f"uptime-kuma returned HTTP {resp.status_code}")

    heartbeats = resp.json().get("heartbeatList") or {}
    up = 0
    total = 0
    for beats in heartbeats.values():
        if not beats:
            continue
        total += 1
        # Uptime Kuma status: 1 = up, everything else (0/2/3) is not up.
        if beats[-1].get("status") == 1:
            up += 1
    return {"up": up, "down": total - up, "total": total}
