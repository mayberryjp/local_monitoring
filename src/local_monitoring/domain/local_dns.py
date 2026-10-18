"""Refresh Mirenai's local DNS zones."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from local_monitoring.config import settings
from local_monitoring.domain.errors import CheckError


def _request(method: str, path: str) -> dict[str, Any]:
    url = f"{settings.mirenai_base_url.rstrip('/')}{path}"
    try:
        resp = requests.request(method, url, timeout=settings.http_timeout_seconds)
    except requests.RequestException as exc:
        raise CheckError("upstream_unreachable", "Mirenai request failed", str(exc)) from exc
    if resp.status_code != 200:
        raise CheckError("upstream_error", f"Mirenai {path} returned HTTP {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise CheckError("upstream_error", "Mirenai returned invalid JSON", str(exc)) from exc
    if not isinstance(data, dict) or data.get("status") != "ok":
        raise CheckError("upstream_error", f"Mirenai {path} returned an invalid response")
    return data


def _zone_ids() -> list[int]:
    # Without limit/offset, Mirenai returns every zone, including disabled ones.
    zones = _request("GET", "/local-zones").get("local_zones")
    if not isinstance(zones, list):
        raise CheckError("upstream_error", "Mirenai returned an invalid local zone list")
    ids: list[int] = []
    for zone in zones:
        zone_id = zone.get("id") if isinstance(zone, dict) else None
        if type(zone_id) is not int or zone_id < 1:
            raise CheckError("upstream_error", "Mirenai returned an invalid local zone ID")
        ids.append(zone_id)
    return ids


def _refresh_zone(zone_id: int) -> str | None:
    try:
        _request("POST", f"/local-zones/{zone_id}/refresh")
    except CheckError as exc:
        detail = f": {exc.detail}" if exc.detail else ""
        return f"zone {zone_id}: {exc.message}{detail}"
    return None


def refresh_all() -> dict[str, Any]:
    """Wait for all zone refreshes and report partial failures rather than hiding them."""
    if not settings.mirenai_base_url:
        raise CheckError("not_configured", "Mirenai is not configured; set MIRENAI_BASE_URL")

    zone_ids = _zone_ids()
    with ThreadPoolExecutor(max_workers=8) as executor:
        failures = [error for error in executor.map(_refresh_zone, zone_ids) if error is not None]
    refreshed = len(zone_ids) - len(failures)
    summary = f"local DNS: {refreshed} of {len(zone_ids)} zones refreshed; {len(failures)} failed"
    try:
        _zone_ids()
    except CheckError as exc:
        raise CheckError(
            "upstream_error",
            f"{summary}; could not reload the zone list",
            "\n".join([*failures, exc.message, exc.detail or ""]),
        ) from exc
    if failures:
        raise CheckError("upstream_error", summary, "\n".join(failures))
    return {"message": summary, "refreshed": refreshed, "failed": 0}
