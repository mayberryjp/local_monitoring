"""Check that every container in the per-site blob has an Uptime Kuma v2 docker monitor."""

from __future__ import annotations

from typing import Any

from local_monitoring.config import settings
from local_monitoring.domain import uptime_kuma_v2
from local_monitoring.domain.errors import CheckError


def _docker_monitor_tokens(base_url: str, api_key: str) -> set[str]:
    """Upper-cased last word of each ``docker``-type monitor name (``... HOMEASSISTANT``)."""
    monitors = uptime_kuma_v2.fetch_monitors(base_url, api_key)
    return {
        uptime_kuma_v2.last_token(m["name"])
        for m in monitors
        if m.get("type") == "docker" and m.get("name")
    }


def collect() -> dict[str, Any]:
    if not settings.container_blob_url or not settings.uptime_kuma_v2_api_base_url:
        raise CheckError("not_configured", "docker-monitors check is not configured")

    containers = uptime_kuma_v2.fetch_name_list(settings.container_blob_url, "container blob")
    monitor_tokens = _docker_monitor_tokens(
        settings.uptime_kuma_v2_api_base_url.rstrip("/"),
        settings.uptime_kuma_v2_api_key,
    )

    # Monitored when the upper-cased container name is the last word of a docker
    # monitor's name, e.g. "homeassistant" -> "AZURE CONTAINER HOMEASSISTANT".
    unmonitored_containers = [c for c in containers if c.upper() not in monitor_tokens]
    total = len(containers)
    return {
        "monitored": total - len(unmonitored_containers),
        "unmonitored": len(unmonitored_containers),
        "total": total,
        "unmonitored_containers": unmonitored_containers,
    }
