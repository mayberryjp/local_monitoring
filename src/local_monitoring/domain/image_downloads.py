"""Read active image pull progress from docker-updater."""

from __future__ import annotations

from typing import Any

import requests
from pydantic import BaseModel, ConfigDict, Field

from local_monitoring.config import settings
from local_monitoring.domain.errors import CheckError


class _Pull(BaseModel):
    model_config = ConfigDict(strict=True, allow_inf_nan=False)

    id: str = Field(min_length=1)
    image: str = Field(min_length=1)
    container: str = Field(min_length=1)
    host_id: str = Field(min_length=1)
    started_at: str = Field(min_length=1)
    progress_bytes: int = Field(ge=0)
    total_bytes: int | None = Field(ge=0)
    percent_complete: float | None = Field(ge=0, le=100)


class _PullsResponse(BaseModel):
    model_config = ConfigDict(strict=True)

    pulls: list[_Pull]


def collect() -> dict[str, Any]:
    if not settings.docker_updater_base_url:
        raise CheckError("not_configured", "docker-updater is not configured")

    url = f"{settings.docker_updater_base_url.rstrip('/')}/api/pulls"
    try:
        resp = requests.get(url, timeout=settings.http_timeout_seconds, allow_redirects=False)
    except requests.RequestException as exc:
        raise CheckError(
            "upstream_unreachable", "docker-updater pull progress request failed", str(exc)
        ) from exc
    if resp.status_code != 200:
        message = f"docker-updater pull progress returned HTTP {resp.status_code}"
        if resp.status_code == 404:
            message += "; deploy a docker-updater version supporting GET /api/pulls"
        raise CheckError("upstream_error", message)

    try:
        return _PullsResponse.model_validate(resp.json()).model_dump()
    except ValueError as exc:
        raise CheckError(
            "upstream_error", "docker-updater returned invalid pull progress", str(exc)
        ) from exc
