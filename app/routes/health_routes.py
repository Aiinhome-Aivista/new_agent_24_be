from flask import Blueprint
from app.errors.handlers import ok

health_bp = Blueprint("health", __name__)


@health_bp.route("/health", methods=["GET"])
def health():
    return ok({"status": "ok", "service": "tdd-intelligence-backend"})
