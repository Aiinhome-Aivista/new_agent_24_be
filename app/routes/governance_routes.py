from flask import Blueprint, request
from app.errors.handlers import ok
from app.auth.decorators import require_auth, require_permission
from app.audit.audit_log import list_events, list_guardrail_events

governance_bp = Blueprint("governance", __name__)


@governance_bp.route("/audit", methods=["GET"])
@require_auth
@require_permission("audit.read")
def audit_events():
    wf = request.args.get("workflow_id")
    return ok({"events": list_events(wf)})


@governance_bp.route("/guardrails", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def guardrails():
    wf = request.args.get("workflow_id")
    return ok({"events": list_guardrail_events(wf)})
