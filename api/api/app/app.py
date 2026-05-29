"""Flask application — REST API exposing the model registry/console endpoints."""
from __future__ import annotations

import os

from flask import jsonify
from werkzeug.exceptions import HTTPException

from .functions import *
from . import routes


def _register_error_handlers(app):
    """Always return JSON on error so the frontend can read a real message
    instead of choking on Flask's default HTML error pages."""

    @app.errorhandler(HTTPException)
    def _handle_http_exc(exc):
        # abort(code, description=...) lands here — surface the description.
        return jsonify({"error": exc.description or exc.name, "status": exc.code}), exc.code

    @app.errorhandler(Exception)
    def _handle_uncaught(exc):
        # Unhandled errors (e.g. HfApi raising on a 401) become JSON 500s
        # carrying the underlying message rather than an HTML stack page.
        return jsonify({"error": f"{type(exc).__name__}: {exc}", "status": 500}), 500

    return app


def create_app():
    """Build the Flask app, registering every blueprint found in ``routes``."""
    app = get_Flask_app(
        name="abstractgpt_api",
        routes=routes,
        allowed_origins=[
            "https://dev.abstractgpt.ai/*",
            "https://abstractgpt.ai/*",
            "https://api.abstractgpt.ai/*",
        ],
        debug=True,
    )
    return _register_error_handlers(app)


def run() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    create_app().run(host=host, port=port)
