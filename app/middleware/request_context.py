"""Attaches a request_id to every request for tracing + response envelopes."""
import uuid
from flask import g, request


def register_request_context(app):
    @app.before_request
    def _assign_request_id():
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex

    @app.after_request
    def _echo_request_id(resp):
        resp.headers["X-Request-ID"] = getattr(g, "request_id", "")
        # Secure headers
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp
