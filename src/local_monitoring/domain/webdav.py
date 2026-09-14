"""Reduce a WebDAV pointer file's embedded timestamp to a freshness check."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import requests

from local_monitoring.config import settings
from local_monitoring.domain.errors import CheckError


def _parse_timestamp(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.strip())
    except ValueError:
        return None


def collect() -> dict[str, Any]:
    if not settings.webdav_url:
        raise CheckError("not_configured", "webdav is not configured")

    auth = (settings.webdav_username, settings.webdav_password) if settings.webdav_username else None
    try:
        resp = requests.get(
            settings.webdav_url,
            auth=auth,
            timeout=settings.http_timeout_seconds,
        )
    except requests.RequestException as exc:
        raise CheckError("upstream_unreachable", "webdav request failed", str(exc)) from exc
    if resp.status_code != 200:
        raise CheckError("upstream_error", f"webdav returned HTTP {resp.status_code}")

    modified = _parse_timestamp(resp.text)
    if modified is None:
        raise CheckError("parse_error", "could not parse timestamp from webdav file")

    age_hours = (datetime.now(UTC) - modified).total_seconds() / 3600
    recent = age_hours <= settings.webdav_recent_hours
    return {
        "result": "OK" if recent else "STALE",
        "recent": recent,
        "timestamp": modified.astimezone().isoformat(),
        "age_hours": round(age_hours, 2),
        "threshold_hours": settings.webdav_recent_hours,
    }
