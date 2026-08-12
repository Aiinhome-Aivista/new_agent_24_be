"""Consistent success/error response envelope + centralized error handling."""
import uuid
from flask import jsonify, request, g


def _request_id():
    return getattr(g, "request_id", None) or request.headers.get("X-Request-ID") or uuid.uuid4().hex


def ok(data=None, message="", status=200):
    return jsonify({
        "success": True,
        "data": data if data is not None else {},
        "message": message,
        "request_id": _request_id(),
    }), status


def fail(code, message, status=400, details=None):
    return jsonify({
        "success": False,
        "error": {"code": code, "message": message, "details": details or {}},
        "request_id": _request_id(),
    }), status


class ApiError(Exception):
    def __init__(self, code, message, status=400, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def _api_error(err):
        return fail(err.code, err.message, err.status, err.details)

    @app.errorhandler(404)
    def _not_found(_e):
        return fail("NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _method(_e):
        return fail("METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(500)
    def _server(_e):
        return fail("INTERNAL_ERROR", "Unexpected server error", 500)
