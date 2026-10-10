"""Find Uptime Kuma monitors missing from the configured public status page."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests

from local_monitoring.config import settings
from local_monitoring.domain import uptime_kuma, uptime_kuma_v2
from local_monitoring.domain.errors import CheckError


def _status_page() -> tuple[str, list[dict[str, Any]]]:
    base_url = settings.uptime_kuma_base_url.rstrip("/")
    slug = uptime_kuma.status_page_slug(settings.uptime_kuma_slug)
    if not base_url or not slug:
        raise CheckError("not_configured", "uptime-kuma base URL and status-page slug are required")

    try:
        resp = requests.get(
            f"{base_url}/api/status-page/{quote(slug, safe='')}",
            timeout=settings.http_timeout_seconds,
        )
    except requests.RequestException as exc:
        raise CheckError("upstream_unreachable", "uptime-kuma status-page request failed", str(exc)) from exc
    if resp.status_code != 200:
        raise CheckError("upstream_error", f"uptime-kuma status page returned HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise CheckError("upstream_error", "uptime-kuma status page returned invalid JSON", str(exc)) from exc
    if not isinstance(payload, dict):
        raise CheckError("upstream_error", "uptime-kuma status page returned an unexpected response")
    groups = payload.get("publicGroupList") or []
    if not isinstance(groups, list):
        raise CheckError("upstream_error", "uptime-kuma status page returned an invalid group list")
    return slug, groups


def _listed_monitor_ids(groups: list[dict[str, Any]]) -> set[str]:
    return {
        str(monitor["id"])
        for group in groups
        if isinstance(group, dict)
        for monitor in (group.get("monitorList") or [])
        if isinstance(monitor, dict) and monitor.get("id") is not None
    }


def _missing_monitors() -> tuple[str, list[dict[str, Any]]]:
    if not settings.uptime_kuma_v2_api_base_url:
        raise CheckError("not_configured", "uptime-kuma-v2-api is not configured")

    monitors = uptime_kuma_v2.fetch_monitors(
        settings.uptime_kuma_v2_api_base_url.rstrip("/"), settings.uptime_kuma_v2_api_key
    )
    slug, groups = _status_page()
    listed_ids = _listed_monitor_ids(groups)
    missing = [
        {"id": monitor["id"], "name": str(monitor.get("name") or monitor["id"]), "type": monitor.get("type")}
        for monitor in monitors
        if monitor.get("id") is not None and str(monitor["id"]) not in listed_ids
    ]
    return slug, missing


def collect() -> dict[str, Any]:
    slug, missing = _missing_monitors()
    return {
        "status_page": slug,
        "listed": len(missing) == 0,
        "missing": len(missing),
        "unlisted_monitors": missing,
    }


def add_monitor(monitor_id: int) -> dict[str, Any]:
    """Add one currently-unlisted Uptime Kuma monitor to the default status-page group."""
    target = str(monitor_id)
    slug, missing = _missing_monitors()
    monitor = next((item for item in missing if str(item["id"]) == target), None)
    if monitor is None:
        raise CheckError("not_found", f"monitor {monitor_id!r} is not currently missing from the status page")

    base_url = settings.uptime_kuma_v2_api_base_url.rstrip("/")
    try:
        resp = requests.post(
            f"{base_url}/v1/statuspages/{quote(slug, safe='')}/monitors",
            headers={"X-API-Key": settings.uptime_kuma_v2_api_key},
            json={"monitor_ids": [monitor_id]},
            timeout=settings.http_timeout_seconds,
        )
    except requests.RequestException as exc:
        raise CheckError("upstream_unreachable", "uptime-kuma-v2-api status-page add request failed", str(exc)) from exc
    if resp.status_code != 200:
        raise CheckError(
            "upstream_error",
            f"uptime-kuma-v2-api status-page add returned HTTP {resp.status_code}",
        )
    try:
        result = resp.json()
    except ValueError:
        result = {}
    return {
        "added": monitor["name"],
        "monitor_id": monitor_id,
        "status_page": slug,
        "message": result.get("msg") if isinstance(result, dict) else None,
    }