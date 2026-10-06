"""Warn about ALLOWED_ADDITIONAL_MONITORS entries that match no Uptime Kuma monitor."""

from __future__ import annotations

from typing import Any

from local_monitoring.config import settings
from local_monitoring.domain import uptime_kuma_v2
from local_monitoring.domain.additional_monitors import allowed_entries
from local_monitoring.domain.errors import CheckError


def collect() -> dict[str, Any]:
    entries = allowed_entries()
    if not entries:
        return {"allowed": 0, "unmatched": 0, "unmatched_allowed": []}
    if not settings.uptime_kuma_v2_api_base_url:
        raise CheckError("not_configured", "allowlist check is not configured")

    base = settings.uptime_kuma_v2_api_base_url.rstrip("/")
    monitors = uptime_kuma_v2.fetch_monitors(base, settings.uptime_kuma_v2_api_key)
    names_upper = [
        name.upper()
        for monitor in monitors
        if (name := str(monitor.get("name") or "").strip())
    ]
    # Stale when the whitelist substring appears in no monitor name (nothing to suppress).
    unmatched = [entry for entry in entries if not any(entry.upper() in nu for nu in names_upper)]
    return {
        "allowed": len(entries),
        "unmatched": len(unmatched),
        "unmatched_allowed": unmatched,
    }
