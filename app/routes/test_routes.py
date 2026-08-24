from flask import Blueprint, request
from app.errors.handlers import ok, fail
from app.auth.decorators import require_auth, require_permission
from app.repositories.test_repo import list_test_cases, set_test_status, list_executions, list_code_quality

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


@test_bp.route("/workflows/<workflow_id>/code-quality", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def code_quality(workflow_id):
    return ok({"code_quality": list_code_quality(workflow_id)})


@test_bp.route("/workflows/<workflow_id>/code-log", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def code_log(workflow_id):
    from app.repositories.workflow_repo import get_run
    run = get_run(workflow_id)
    if not run:
        return fail("NOT_FOUND", "Workflow not found", 404)
    state = run.get("state_json") or {}
    generation_log = state.get("code_generation")
    return ok({"code_log": generation_log})


