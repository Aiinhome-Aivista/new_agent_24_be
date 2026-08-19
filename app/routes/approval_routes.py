from flask import Blueprint, request, g
from app.errors.handlers import ok, fail
from app.auth.decorators import require_auth, require_permission
from app.repositories.evidence_repo import (pending_approvals, approvals_for, decide_approval,
                                             list_evidence, get_evidence, set_evidence_status)
from app.repositories.workflow_repo import get_run
from app.services.workflow_runner import dispatch_resume
from app.audit.audit_log import record as audit
from app.extensions.db import query

approval_bp = Blueprint("approvals", __name__)

_STAGE_MAP = {"TEST_REVIEW": "TEST_REVIEW", "EVIDENCE_REVIEW": "EVIDENCE_REVIEW",
              "ALM_ATTACHMENT": "ALM_APPROVAL"}


@approval_bp.route("/approvals", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def approvals():
    return ok({"approvals": pending_approvals()})


@approval_bp.route("/workflows/<workflow_id>/approvals", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def workflow_approvals(workflow_id):
    return ok({"approvals": approvals_for(workflow_id)})


@approval_bp.route("/approvals/<uuid>/decision", methods=["POST"])
@require_auth
@require_permission("test.review")
def decide(uuid):
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    comment = body.get("comment", "")
    if decision not in ("APPROVED", "REJECTED", "CHANGES_REQUESTED"):
        return fail("VALIDATION_ERROR", "Invalid decision")

    approval = query("SELECT * FROM approvals WHERE uuid=%s", (uuid,), fetchone=True)
    if not approval:
        # Fallback: check if uuid was provided as workflow_id
        approval = query("SELECT * FROM approvals WHERE workflow_id=%s AND decision='PENDING' ORDER BY requested_at DESC LIMIT 1", (uuid,), fetchone=True)
        if approval:
            uuid = approval["uuid"]
    if not approval:
        return fail("NOT_FOUND", "Approval not found", 404)


    decide_approval(uuid, decision, g.user_id, comment)
    audit("approval", user_id=g.user_id, workflow_id=approval["workflow_id"],
          status=decision, metadata={"stage": approval["stage"]})

    resumed = None
    if decision == "APPROVED":
        checkpoint = _STAGE_MAP.get(approval["stage"])
        _, status = dispatch_resume(approval["workflow_id"], checkpoint)
        resumed = status
    return ok({"decision": decision, "resumed": resumed}, "Decision recorded")


@approval_bp.route("/workflows/<workflow_id>/evidence", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def evidence(workflow_id):
    import os
    evs = list_evidence(workflow_id)
    for e in evs:
        if e.get("file_path") and os.path.isfile(e["file_path"]):
            try:
                with open(e["file_path"], "r", encoding="utf-8") as f:
                    e["content"] = f.read()
            except Exception:
                e["content"] = e.get("narrative") or ""
        else:
            e["content"] = e.get("narrative") or ""
    return ok({"evidence": evs})

