"""Reduce an Uptime Kuma status page to a simple up/down counter."""

from __future__ import annotations

from typing import Any

import requests

from local_monitoring.config import settings
from local_monitoring.domain.errors import CheckError


def _fetch_monitor_names(base_url: str, slug: str) -> dict[str, str]:
    """Map monitor id -> name from the status-page config; empty on any failure."""
    try:
        resp = requests.get(
            f"{base_url}/api/status-page/{slug}",
            timeout=settings.http_timeout_seconds,
        )
        if resp.status_code != 200:
            return {}
        groups = resp.json().get("publicGroupList") or []
    except (requests.RequestException, ValueError):
        return {}
    names: dict[str, str] = {}
    for group in groups:
        for monitor in group.get("monitorList") or []:
            monitor_id, name = monitor.get("id"), monitor.get("name")
            if monitor_id is not None and name:
                names[str(monitor_id)] = name
    return names


def collect() -> dict[str, Any]:
    if not settings.uptime_kuma_base_url or not settings.uptime_kuma_slug:
        raise CheckError("not_configured", "uptime-kuma is not configured")

    base_url = settings.uptime_kuma_base_url.rstrip("/")
    slug = settings.uptime_kuma_slug
    url = f"{base_url}/api/status-page/heartbeat/{slug}"
    try:
        resp = requests.get(url, timeout=settings.http_timeout_seconds)
    except requests.RequestException as exc:
        raise CheckError("upstream_unreachable", "uptime-kuma request failed", str(exc)) from exc
    if resp.status_code != 200:
        raise CheckError("upstream_error", f"uptime-kuma returned HTTP {resp.status_code}")

    heartbeats = resp.json().get("heartbeatList") or {}
    up = 0
    total = 0
    down_ids: list[str] = []
    for monitor_id, beats in heartbeats.items():
        if not beats:
            continue
        total += 1
        # Uptime Kuma status: 1 = up, everything else (0/2/3) is not up.
        if beats[-1].get("status") == 1:
            up += 1
        else:
            down_ids.append(monitor_id)

    # Resolve ids to names only when something is down; fall back to the id.
    names = _fetch_monitor_names(base_url, slug) if down_ids else {}
    down_monitors = [names.get(mid, mid) for mid in down_ids]
    return {"up": up, "down": total - up, "total": total, "down_monitors": down_monitors}
