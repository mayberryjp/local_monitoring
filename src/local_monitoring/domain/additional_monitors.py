"""List Uptime Kuma v2 monitors not covered by the container or ping checks."""

from __future__ import annotations

from typing import Any

import requests

from local_monitoring.config import settings
from local_monitoring.domain import uptime_kuma_v2
from local_monitoring.domain.errors import CheckError

# A monitor is "covered" when its last-word token matches a known container (docker
# monitor) or a known device (ping monitor); everything else is "additional".
DOCKER_TYPES = {"docker"}
PING_TYPES = {"ping", "icmp"}


def allowed_entries() -> list[str]:
    """Trimmed ALLOWED_ADDITIONAL_MONITORS substrings, in order, with blanks dropped."""
    return [
        entry.strip()
        for entry in settings.allowed_additional_monitors.split(",")
        if entry.strip()
    ]


def _tokens(blob_urls: str, what: str) -> set[str]:
    if not blob_urls:
        return set()
    return {name.upper() for name in uptime_kuma_v2.fetch_name_list(blob_urls, what)}


def _additional(
    monitors: list[dict[str, Any]],
    container_tokens: set[str],
    device_tokens: set[str],
    allowed_upper: list[str],
) -> list[dict[str, Any]]:
    """Monitors not matched by container/ping coverage and not whitelisted (id + name)."""
    result: list[dict[str, Any]] = []
    for monitor in monitors:
        name = str(monitor.get("name") or "").strip()
        if not name:
            continue
        mtype = monitor.get("type")
        token = uptime_kuma_v2.last_token(name)
        covered = (mtype in DOCKER_TYPES and token in container_tokens) or (
            mtype in PING_TYPES and token in device_tokens
        )
        # Whitelisted when any entry is a (case-insensitive) substring of the name.
        name_upper = name.upper()
        if covered or any(entry in name_upper for entry in allowed_upper):
            continue
        result.append({"id": monitor.get("id"), "name": name})
    return result


def _gather() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (all monitors, additional monitors) for the configured v2 API."""
    base = settings.uptime_kuma_v2_api_base_url.rstrip("/")
    monitors = uptime_kuma_v2.fetch_monitors(base, settings.uptime_kuma_v2_api_key)
    container_tokens = _tokens(settings.container_blob_url, "container blob")
    device_tokens = _tokens(settings.sando_devices_url, "sando devices")
    allowed_upper = [entry.upper() for entry in allowed_entries()]
    return monitors, _additional(monitors, container_tokens, device_tokens, allowed_upper)


def collect() -> dict[str, Any]:
    if not settings.uptime_kuma_v2_api_base_url:
        raise CheckError("not_configured", "additional-monitors check is not configured")

    monitors, additional = _gather()
    return {
        "additional": len(additional),
        "allowed": len(allowed_entries()),
        "total": len(monitors),
        "additional_monitors": [monitor["name"] for monitor in additional],
    }


def delete_monitor(name: str) -> dict[str, Any]:
    """Delete an Uptime Kuma v2 monitor flagged as "additional".

    The name is validated against the live additional set, so a covered or whitelisted
    monitor can't be removed through this action.
    """
    if not settings.uptime_kuma_v2_api_base_url:
        raise CheckError("not_configured", "additional-monitors check is not configured")

    target = name.strip()
    _, additional = _gather()
    match = next((m for m in additional if m["name"] == target and m["id"] is not None), None)
    if match is None:
        raise CheckError("not_found", f"monitor {name!r} is not an additional monitor")

    base = settings.uptime_kuma_v2_api_base_url.rstrip("/")
    try:
        resp = requests.delete(
            f"{base}/v1/monitors/{match['id']}",
            headers={"X-API-Key": settings.uptime_kuma_v2_api_key},
            timeout=settings.http_timeout_seconds,
        )
    except requests.RequestException as exc:
        raise CheckError(
            "upstream_unreachable", "uptime-kuma-v2-api delete request failed", str(exc)
        ) from exc
    if resp.status_code != 200:
        raise CheckError(
            "upstream_error", f"uptime-kuma-v2-api delete returned HTTP {resp.status_code}"
        )
    return {"deleted": target, "monitor_id": match["id"]}
