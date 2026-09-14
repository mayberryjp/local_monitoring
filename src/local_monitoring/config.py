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


settings = Settings()
