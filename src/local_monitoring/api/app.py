"""Bottle application factory."""

from __future__ import annotations

import json
from typing import Any

from bottle import Bottle, JSONPlugin, response

from local_monitoring.api.routes.checks import register_check_routes
from local_monitoring.api.routes.dashboard import register_dashboard_routes
from local_monitoring.api.routes.health import register_health_routes

SERVICE_NAME = "local-monitoring-api"


def create_app() -> Bottle:
    app = Bottle()
    app.title = SERVICE_NAME

    # Pretty-print every JSON response by replacing Bottle's default compact encoder.
    app.uninstall(JSONPlugin)
    app.install(JSONPlugin(json_dumps=lambda body: json.dumps(body, indent=2)))

    register_health_routes(app)
    register_check_routes(app)
    register_dashboard_routes(app)

    @app.hook("after_request")
    def enable_cors() -> None:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"

    @app.route("/<path:path>", method="OPTIONS")
    def cors_preflight(path: str) -> str:
        return ""

    @app.error(404)
    def not_found(_err: Any) -> str:
        response.content_type = "application/json"
        return json.dumps({"status": "error", "code": "not_found", "error": "not found"}, indent=2)

    return app


app = create_app()
