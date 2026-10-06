"""Check that every SANDO device has an Uptime Kuma v2 ping/icmp monitor."""

from __future__ import annotations

from typing import Any

import requests

from local_monitoring.config import settings
from local_monitoring.domain import uptime_kuma_v2
from local_monitoring.domain.errors import CheckError

# Uptime Kuma's ping probe is type ``ping``; accept ``icmp`` too for forward safety.
PING_TYPES = {"ping", "icmp"}


def _ping_monitor_tokens(base_url: str, api_key: str) -> set[str]:
    """Upper-cased last word of each ping/icmp monitor name (``OFFICE PING NETGEARSWITCH``)."""
    monitors = uptime_kuma_v2.fetch_monitors(base_url, api_key)
    return {
        uptime_kuma_v2.last_token(m["name"])
        for m in monitors
        if m.get("type") in PING_TYPES and m.get("name")
    }


def _parse_interval(raw: str) -> int:
    """Clamp a device line's interval to Uptime Kuma's accepted bounds (20-86400s)."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 86400
    return max(20, min(86400, value))


def _device_records(text: str) -> list[dict[str, Any]]:
    """Parse ``ip,domain,interval`` device lines into monitor-ready records, de-duplicated."""
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = [f.strip() for f in line.split(",")]
        if len(fields) < 2:
            continue
        domain = fields[1]
        labels = domain.split(".")
        device = labels[0]
        key = device.lower()
        if not device or key in seen:
            continue
        seen.add(key)
        site = labels[1] if len(labels) > 1 else ""
        ip = fields[0]
        records.append(
            {
                "device": device,
                "site": site,
                "hostname": ip or domain,
                "interval": _parse_interval(fields[2] if len(fields) > 2 else ""),
            }
        )
    return records


def collect() -> dict[str, Any]:
    if not settings.sando_devices_url or not settings.uptime_kuma_v2_api_base_url:
        raise CheckError("not_configured", "ping-monitors check is not configured")

    devices = uptime_kuma_v2.fetch_name_list(settings.sando_devices_url, "sando devices")
    monitor_tokens = _ping_monitor_tokens(
        settings.uptime_kuma_v2_api_base_url.rstrip("/"),
        settings.uptime_kuma_v2_api_key,
    )

    # Monitored when the upper-cased device name is the last word of a ping monitor's
    # name, e.g. "netgearswitch" -> "OFFICE PING NETGEARSWITCH".
    unmonitored_devices = [d for d in devices if d.upper() not in monitor_tokens]
    total = len(devices)
    return {
        "monitored": total - len(unmonitored_devices),
        "unmonitored": len(unmonitored_devices),
        "total": total,
        "unmonitored_devices": unmonitored_devices,
    }


def add_ping_monitor(device: str) -> dict[str, Any]:
    """Create an Uptime Kuma v2 ping monitor for a device from the SANDO list.

    The monitor name/hostname/interval come from the authoritative SANDO blob, not from
    the caller, so an unknown device is rejected rather than used to craft an arbitrary
    monitor.
    """
    if not settings.sando_devices_url or not settings.uptime_kuma_v2_api_base_url:
        raise CheckError("not_configured", "ping-monitors check is not configured")

    wanted = device.strip().lower()
    text = uptime_kuma_v2.fetch_blob_text(settings.sando_devices_url, "sando devices")
    record = next((r for r in _device_records(text) if r["device"].lower() == wanted), None)
    if record is None:
        raise CheckError("not_found", f"device {device!r} is not in the SANDO devices list")

    name = " ".join(part for part in (record["site"], "PING", record["device"]) if part).upper()
    payload = {
        "type": "ping",
        "name": name,
        "hostname": record["hostname"],
        "interval": record["interval"],
    }
    base = settings.uptime_kuma_v2_api_base_url.rstrip("/")
    try:
        resp = requests.post(
            f"{base}/v1/monitors",
            headers={"X-API-Key": settings.uptime_kuma_v2_api_key},
            json=payload,
            timeout=settings.http_timeout_seconds,
        )
    except requests.RequestException as exc:
        raise CheckError(
            "upstream_unreachable", "uptime-kuma-v2-api create request failed", str(exc)
        ) from exc
    if resp.status_code != 200:
        raise CheckError(
            "upstream_error", f"uptime-kuma-v2-api create returned HTTP {resp.status_code}"
        )

    try:
        body = resp.json()
    except ValueError:
        body = {}
    monitor_id = body.get("monitorID") if isinstance(body, dict) else None
    return {"created": name, "monitor_id": monitor_id, "hostname": record["hostname"]}
