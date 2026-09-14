"""API process entrypoint (served by Waitress under supervisord)."""

from __future__ import annotations

from waitress import serve

from local_monitoring.api.app import create_app
from local_monitoring.config import settings
from local_monitoring.logging import configure_logging, get_logger


def main() -> None:
    configure_logging(settings.log_level)
    log = get_logger("local_monitoring.api")
    app = create_app()
    log.info("starting api on %s:%s", settings.api_listen_address, settings.api_port)
    serve(app, host=settings.api_listen_address, port=settings.api_port)


if __name__ == "__main__":
    main()
