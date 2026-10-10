"""Application configuration loaded from environment variables."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    api_listen_address: str = Field("0.0.0.0", validation_alias="API_LISTEN_ADDRESS")  # nosec B104
    api_port: int = Field(8000, validation_alias="API_PORT")
    log_level: str = Field("INFO", validation_alias="LOG_LEVEL")
    http_timeout_seconds: float = Field(10.0, validation_alias="HTTP_TIMEOUT_SECONDS")

    # Uptime Kuma status page -> up/down counter.
    uptime_kuma_base_url: str = Field("", validation_alias="UPTIME_KUMA_BASE_URL")
    uptime_kuma_slug: str = Field("", validation_alias="UPTIME_KUMA_SLUG")

    # WebDAV single-file freshness check.
    webdav_url: str = Field("", validation_alias="WEBDAV_URL")
    webdav_username: str = Field("", validation_alias="WEBDAV_USERNAME")
    webdav_password: str = Field("", validation_alias="WEBDAV_PASSWORD")
    webdav_recent_hours: float = Field(24.0, validation_alias="WEBDAV_RECENT_HOURS")

    # docker-updater pending-updates count.
    docker_updater_base_url: str = Field("", validation_alias="DOCKER_UPDATER_BASE_URL")

    # Docker socket for the running/stopped container count.
    docker_host: str = Field("unix:///var/run/docker.sock", validation_alias="DOCKER_HOST")

    # Browser-reachable URLs for the dashboard's section-title links. These are the
    # public endpoints a remote client can open, distinct from the internal base URLs
    # used for server-to-server calls. Blank -> the title renders as plain text.
    uptime_kuma_public_url: str = Field("", validation_alias="UPTIME_KUMA_PUBLIC_URL")
    portainer_url: str = Field("", validation_alias="PORTAINER_URL")
    portainer_api_key: str = Field("", validation_alias="PORTAINER_API_KEY")
    docker_updater_public_url: str = Field("", validation_alias="DOCKER_UPDATER_PUBLIC_URL")
    compose_cache_ttl_seconds: int = Field(300, validation_alias="COMPOSE_CACHE_TTL_SECONDS")

    # GitHub Compose source URL, including its site directory, e.g.
    # ``https://github.com/mayberryjp/dockercompose/house``.
    docker_compose: str = Field("", validation_alias="DOCKER_COMPOSE")

    # Per-site container list(s) -> Uptime Kuma v2 docker-monitor coverage.
    # CONTAINER_BLOB may be a single URL or a comma-separated list that is merged.
    container_blob_url: str = Field("", validation_alias="CONTAINER_BLOB")
    uptime_kuma_v2_api_base_url: str = Field("", validation_alias="UPTIME_KUMA_V2_API_BASE_URL")
    uptime_kuma_v2_api_key: str = Field("", validation_alias="UPTIME_KUMA_V2_API_KEY")

    # Per-site device list -> Uptime Kuma v2 ping-monitor coverage. SANDO_DEVICES_URL
    # lines are ``ip_address,domain_name,interval`` (same shape as CONTAINER_BLOB); a
    # device is the first DNS label of the 2nd field.
    sando_devices_url: str = Field("", validation_alias="SANDO_DEVICES_URL")

    # Uptime Kuma monitors deliberately not tied to a container or device. A
    # comma-separated list of case-insensitive substrings; a monitor is excluded from
    # the "additional monitors" check when any entry appears anywhere in its name.
    allowed_additional_monitors: str = Field("", validation_alias="ALLOWED_ADDITIONAL_MONITORS")


settings = Settings()
