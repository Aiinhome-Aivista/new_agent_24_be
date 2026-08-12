from flask import Blueprint, request
from app.errors.handlers import ok, fail
from app.auth.decorators import require_auth, require_permission
from app.repositories.test_repo import list_test_cases, set_test_status, list_executions

test_bp = Blueprint("tests", __name__)


@test_bp.route("/workflows/<workflow_id>/test-cases", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def test_cases(workflow_id):
    return ok({"test_cases": list_test_cases(workflow_id)})


@test_bp.route("/test-cases/<uuid>/status", methods=["POST"])
@require_auth
@require_permission("test.review")
def update_test_status(uuid):
    body = request.get_json(silent=True) or {}
    status = body.get("status")
    if status not in ("APPROVED", "REJECTED", "MODIFIED", "AWAITING_REVIEW"):
        return fail("VALIDATION_ERROR", "Invalid status")
    set_test_status(uuid, status)
    return ok({}, f"Test case {status}")


@test_bp.route("/workflows/<workflow_id>/executions", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def executions(workflow_id):
    return ok({"executions": list_executions(workflow_id)})
