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

_STAGE_MAP = {
    "TEST_REVIEW": "TEST_REVIEW",
    "EVIDENCE_REVIEW": "EVIDENCE_REVIEW",
    "ALM_APPROVAL": "ALM_APPROVAL",
    "ALM_ATTACHMENT": "ALM_APPROVAL",
}


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

    if approval.get("decision") != "PENDING":
        return ok({"decision": approval["decision"], "already_decided": True}, "Approval has already been recorded")

    decide_approval(uuid, decision, g.user_id, comment)
    audit("approval", user_id=g.user_id, workflow_id=approval["workflow_id"],
          status=decision, metadata={"stage": approval["stage"]})

    resumed = None
    if decision == "APPROVED":
        checkpoint = _STAGE_MAP.get(approval["stage"], approval["stage"])
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


@approval_bp.route("/workflows/<workflow_id>/evidence/download", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def download_evidence(workflow_id):
    import os
    from flask import send_file, Response
    fmt = request.args.get("format", "html").lower()
    evs = list_evidence(workflow_id)
    if not evs:
        return fail("NOT_FOUND", "No evidence artifacts found for this workflow", 404)

    latest = evs[-1]
    base_file = latest.get("file_path") or ""
    key = latest.get("evidence_key") or f"EVID-{workflow_id[:8]}"

    if fmt == "html":
        html_file = base_file.replace(".md", ".html")
        if os.path.isfile(html_file):
            return send_file(html_file, mimetype="text/html", as_attachment=True, download_name=f"{key}.html")
        # Generate on the fly if needed
        run = get_run(workflow_id)
        from app.repositories.test_repo import list_test_cases, get_execution_run, get_code_quality_run
        from app.tools.document_generator.generator import render_evidence_html
        content = render_evidence_html(
            key,
            (run.get("state_json") or {}).get("story") or {},
            list_test_cases(workflow_id),
            get_execution_run(workflow_id),
            get_code_quality_run(workflow_id),
            latest.get("narrative", ""),
            latest.get("checksum_sha256", "")
        )
        return Response(content, mimetype="text/html", headers={"Content-Disposition": f"attachment; filename={key}.html"})

    elif fmt == "json":
        import json as _json
        run = get_run(workflow_id)
        from app.repositories.test_repo import list_test_cases, get_execution_run, get_code_quality_run
        bundle = {
            "evidence_key": key,
            "workflow_id": workflow_id,
            "checksum_sha256": latest.get("checksum_sha256"),
            "story": (run.get("state_json") or {}).get("story") or {},
            "test_cases": list_test_cases(workflow_id),
            "execution": get_execution_run(workflow_id),
            "code_quality": get_code_quality_run(workflow_id),
            "narrative": latest.get("narrative"),
            "generated_at": latest.get("created_at"),
        }
        return Response(_json.dumps(bundle, indent=2, default=str), mimetype="application/json",
                        headers={"Content-Disposition": f"attachment; filename={key}-bundle.json"})
    else:
        # Default markdown
        if os.path.isfile(base_file):
            return send_file(base_file, mimetype="text/markdown", as_attachment=True, download_name=f"{key}.md")
        return Response(latest.get("narrative") or "Evidence file not found", mimetype="text/markdown",
                        headers={"Content-Disposition": f"attachment; filename={key}.md"})


@approval_bp.route("/workflows/<workflow_id>/alm-preview", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def alm_preview(workflow_id):
    from app.tools.alm.adapter import generate_alm_payload
    from app.repositories.test_repo import get_execution_run, get_code_quality_run
    provider = request.args.get("provider", "azure_devops")
    run = get_run(workflow_id)
    if not run:
        return fail("NOT_FOUND", "Workflow not found", 404)

    evs = list_evidence(workflow_id)
    latest = evs[-1] if evs else {}
    evidence_key = latest.get("evidence_key") or f"EVID-{workflow_id[:8]}"
    story_key = run.get("story_key") or "STORY-101"
    narrative = latest.get("narrative") or "TDD Verification and execution logs."

    preview = generate_alm_payload(
        provider,
        story_key,
        evidence_key,
        narrative,
        get_execution_run(workflow_id),
        get_code_quality_run(workflow_id)
    )
    return ok({"preview": preview})


