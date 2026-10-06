"""List Uptime Kuma v2 monitors not covered by the container or ping checks."""

from __future__ import annotations

from typing import Any

from local_monitoring.config import settings
from local_monitoring.domain import uptime_kuma_v2
from local_monitoring.domain.errors import CheckError

# A monitor is "covered" when its last-word token matches a known container (docker
# monitor) or a known device (ping monitor); everything else is "additional".
DOCKER_TYPES = {"docker"}
PING_TYPES = {"ping", "icmp"}


def _allowed() -> set[str]:
    """Upper-cased whitelist of monitor names/tokens from ALLOWED_ADDITIONAL_MONITORS."""
    return {
        entry.strip().upper()
        for entry in settings.allowed_additional_monitors.split(",")
        if entry.strip()
    }


def _tokens(blob_urls: str, what: str) -> set[str]:
    if not blob_urls:
        return set()
    return {name.upper() for name in uptime_kuma_v2.fetch_name_list(blob_urls, what)}


def collect() -> dict[str, Any]:
    if not settings.uptime_kuma_v2_api_base_url:
        raise CheckError("not_configured", "additional-monitors check is not configured")

    base = settings.uptime_kuma_v2_api_base_url.rstrip("/")
    monitors = uptime_kuma_v2.fetch_monitors(base, settings.uptime_kuma_v2_api_key)
    container_tokens = _tokens(settings.container_blob_url, "container blob")
    device_tokens = _tokens(settings.sando_devices_url, "sando devices")
    allowed = _allowed()

    additional_monitors: list[str] = []
    for monitor in monitors:
        name = str(monitor.get("name") or "").strip()
        if not name:
            continue
        mtype = monitor.get("type")
        token = uptime_kuma_v2.last_token(name)
        covered = (mtype in DOCKER_TYPES and token in container_tokens) or (
            mtype in PING_TYPES and token in device_tokens
        )
        if covered or name.upper() in allowed or token in allowed:
            continue
        additional_monitors.append(name)

    return {
        "additional": len(additional_monitors),
        "allowed": len(allowed),
        "total": len(monitors),
        "additional_monitors": additional_monitors,
    }
