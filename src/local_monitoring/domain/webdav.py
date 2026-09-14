"""Reduce a WebDAV file's last-modified time to a freshness check."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import requests
from defusedxml.ElementTree import ParseError, fromstring

from local_monitoring.config import settings
from local_monitoring.domain.errors import CheckError

_PROPFIND_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:propfind xmlns:d="DAV:"><d:prop><d:getlastmodified/></d:prop></d:propfind>'
)


def _parse_last_modified(xml_text: str) -> datetime | None:
    try:
        root = fromstring(xml_text)
    except ParseError:
        return None
    for elem in root.iter("{DAV:}getlastmodified"):
        if elem.text:
            try:
                return parsedate_to_datetime(elem.text)
            except (TypeError, ValueError):
                return None
    return None


def collect() -> dict[str, Any]:
    if not settings.webdav_url:
        raise CheckError("not_configured", "webdav is not configured")

    auth = (settings.webdav_username, settings.webdav_password) if settings.webdav_username else None
    try:
        resp = requests.request(
            "PROPFIND",
            settings.webdav_url,
            data=_PROPFIND_BODY,
            headers={"Depth": "0", "Content-Type": "application/xml"},
            auth=auth,
            timeout=settings.http_timeout_seconds,
        )
    except requests.RequestException as exc:
        raise CheckError("upstream_unreachable", "webdav request failed", str(exc)) from exc
    if resp.status_code not in (200, 207):
        raise CheckError("upstream_error", f"webdav returned HTTP {resp.status_code}")

    modified = _parse_last_modified(resp.text)
    if modified is None:
        raise CheckError("parse_error", "could not read last-modified time from webdav response")

    age_hours = (datetime.now(UTC) - modified).total_seconds() / 3600
    recent = age_hours <= settings.webdav_recent_hours
    return {
        "result": "OK" if recent else "STALE",
        "recent": recent,
        "timestamp": modified.astimezone().isoformat(),
        "age_hours": round(age_hours, 2),
        "threshold_hours": settings.webdav_recent_hours,
    }
