"""Check that every container in the per-site blob has an Uptime Kuma v2 docker monitor."""

from __future__ import annotations

from typing import Any

import requests

from local_monitoring.config import settings
from local_monitoring.domain.errors import CheckError


def _parse_container_names(text: str) -> list[str]:
    """First DNS label of each line's second CSV field (``_,a.b.c,...`` -> ``a``), de-duplicated."""
    names: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split(",")
        if len(fields) < 2:
            continue
        container = fields[1].split(".", 1)[0].strip()
        key = container.lower()
        if container and key not in seen:
            seen.add(key)
            names.append(container)
    return names


def _fetch_container_list(url: str) -> list[str]:
    try:
        resp = requests.get(url, timeout=settings.http_timeout_seconds)
    except requests.RequestException as exc:
        raise CheckError("upstream_unreachable", "container blob request failed", str(exc)) from exc
    if resp.status_code != 200:
        raise CheckError("upstream_error", f"container blob returned HTTP {resp.status_code}")
    return _parse_container_names(resp.text)


def _fetch_docker_monitor_tokens(base_url: str, api_key: str) -> set[str]:
    """Upper-cased last word of each ``docker``-type monitor name (``... HOMEASSISTANT``)."""
    try:
        resp = requests.get(
            f"{base_url}/v1/monitors",
            headers={"X-API-Key": api_key},
            timeout=settings.http_timeout_seconds,
        )
    except requests.RequestException as exc:
        raise CheckError(
            "upstream_unreachable", "uptime-kuma-v2-api request failed", str(exc)
        ) from exc
    if resp.status_code != 200:
        raise CheckError("upstream_error", f"uptime-kuma-v2-api returned HTTP {resp.status_code}")

    monitors = resp.json().get("monitors") or []
    tokens: set[str] = set()
    for m in monitors:
        if m.get("type") != "docker" or not m.get("name"):
            continue
        words = str(m["name"]).strip().upper().split()
        if words:
            tokens.add(words[-1])
    return tokens


def collect() -> dict[str, Any]:
    if not settings.container_blob_url or not settings.uptime_kuma_v2_api_base_url:
        raise CheckError("not_configured", "docker-monitors check is not configured")

    containers = _fetch_container_list(settings.container_blob_url)
    monitor_tokens = _fetch_docker_monitor_tokens(
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
