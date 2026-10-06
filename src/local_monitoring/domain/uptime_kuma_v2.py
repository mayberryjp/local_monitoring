"""Shared helpers for the uptime-kuma-v2-api and the per-site device/container blobs."""

from __future__ import annotations

from typing import Any

import requests

from local_monitoring.config import settings
from local_monitoring.domain.errors import CheckError


def parse_names(text: str) -> list[str]:
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
        name = fields[1].split(".", 1)[0].strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    return names


def _fetch_text(url: str, what: str) -> str:
    try:
        resp = requests.get(url, timeout=settings.http_timeout_seconds)
    except requests.RequestException as exc:
        raise CheckError("upstream_unreachable", f"{what} request failed", str(exc)) from exc
    if resp.status_code != 200:
        raise CheckError("upstream_error", f"{what} returned HTTP {resp.status_code}")
    return resp.text


def fetch_blob_text(blob_urls: str, what: str) -> str:
    """Fetch every comma-separated blob URL and join the bodies with newlines."""
    urls = [u.strip() for u in blob_urls.split(",") if u.strip()]
    return "\n".join(_fetch_text(url, what) for url in urls)


def fetch_name_list(blob_urls: str, what: str) -> list[str]:
    """Fetch the blob URL(s) and reduce them to de-duplicated device/container names."""
    return parse_names(fetch_blob_text(blob_urls, what))


def fetch_monitors(base_url: str, api_key: str) -> list[dict[str, Any]]:
    """Return the raw monitor list from the uptime-kuma-v2-api ``/v1/monitors`` endpoint."""
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
    return resp.json().get("monitors") or []


def last_token(name: str) -> str:
    """Upper-cased last whitespace-delimited word of a monitor name (``"" -> ""``)."""
    words = str(name).strip().upper().split()
    return words[-1] if words else ""
