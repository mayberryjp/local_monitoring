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


def _container_records(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = [field.strip() for field in line.split(",")]
        if len(fields) < 2:
            continue
        labels = fields[1].split(".")
        container = labels[0].strip()
        key = container.lower()
        if not container or key in seen:
            continue
        seen.add(key)
        records.append({"container": container, "site": labels[1] if len(labels) > 1 else ""})
    return records


def add_docker_monitor(container: str, host_id: int) -> dict[str, Any]:
    """Create a Docker monitor for a currently-unmonitored configured container."""
    if not settings.container_blob_url or not settings.uptime_kuma_v2_api_base_url:
        raise CheckError("not_configured", "docker-monitors check is not configured")

    wanted = container.strip().lower()
    records = _container_records(
        uptime_kuma_v2.fetch_blob_text(settings.container_blob_url, "container blob")
    )
    record = next((r for r in records if r["container"].lower() == wanted), None)
    if record is None:
        raise CheckError("not_found", f"container {container!r} is not in the container list")

    base = settings.uptime_kuma_v2_api_base_url.rstrip("/")
    monitors = uptime_kuma_v2.fetch_monitors(base, settings.uptime_kuma_v2_api_key)
    monitor_tokens = {
        uptime_kuma_v2.last_token(m["name"])
        for m in monitors
        if m.get("type") == "docker" and m.get("name")
    }
    if record["container"].upper() in monitor_tokens:
        raise CheckError("conflict", f"container {record['container']!r} already has a Docker monitor")

    hosts = uptime_kuma_v2.fetch_docker_hosts()
    host = next((item for item in hosts if str(item.get("id")) == str(host_id)), None)
    if host is None:
        raise CheckError("not_found", f"Docker host {host_id!r} is not configured in Uptime Kuma")

    name = " ".join(
        part for part in (record["site"], "CONTAINER", record["container"]) if part
    ).upper()
    result = uptime_kuma_v2.create_monitor(
        {
            "type": "docker",
            "name": name,
            "docker_host": host_id,
            "docker_container": record["container"],
        }
    )
    return {
        "created": name,
        "monitor_id": result["monitor_id"],
        "container": record["container"],
        "docker_host": host_id,
        "status_page": result["status_page"],
    }
