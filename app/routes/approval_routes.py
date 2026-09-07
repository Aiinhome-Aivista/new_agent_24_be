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
    "TEST_PLAN_REVIEW": "TEST_PLAN_REVIEW",
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
    elif decision == "REJECTED":
        from app.repositories.workflow_repo import update_run, get_run
        run = get_run(approval["workflow_id"])
        if run:
            update_run(approval["workflow_id"], "CANCELLED", run.get("current_stage"), run.get("state_json") or {})
        resumed = "CANCELLED"
        
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
def download_evidence(workflow_id):
    import os
    from flask import Response
    fmt = request.args.get("format", "html").lower()
    evs = list_evidence(workflow_id)
    if not evs:
        return fail("NOT_FOUND", "No evidence artifacts found for this workflow", 404)

    latest = evs[-1]
    base_file = latest.get("file_path") or ""
    key = latest.get("evidence_key") or f"EVID-{workflow_id[:8]}"

    if fmt in ("docx", "word"):
        docx_file = os.path.abspath(base_file.replace(".md", ".docx"))
        if not os.path.isfile(docx_file):
            # Generate docx on the fly
            run = get_run(workflow_id)
            from app.repositories.test_repo import list_test_cases, get_execution_run, get_code_quality_run
            from app.tools.document_generator.generator import render_evidence_docx
            render_evidence_docx(
                key,
                (run.get("state_json") or {}).get("story") or {},
                list_test_cases(workflow_id),
                get_execution_run(workflow_id),
                get_code_quality_run(workflow_id),
                latest.get("narrative", ""),
                latest.get("checksum_sha256", ""),
                docx_file,
                workflow_id=workflow_id
            )
        if os.path.isfile(docx_file):
            with open(docx_file, "rb") as f:
                data = f.read()
            return Response(data, mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            headers={"Content-Disposition": f"attachment; filename={key}.docx"})
        return fail("NOT_FOUND", "Word document generation failed", 404)

    elif fmt == "pdf":
        pdf_file = os.path.abspath(base_file.replace(".md", ".pdf"))
        if not os.path.isfile(pdf_file):
            # Generate pdf on the fly
            run = get_run(workflow_id)
            from app.repositories.test_repo import list_test_cases, get_execution_run, get_code_quality_run
            from app.tools.document_generator.generator import render_evidence_pdf
            render_evidence_pdf(
                key,
                (run.get("state_json") or {}).get("story") or {},
                list_test_cases(workflow_id),
                get_execution_run(workflow_id),
                get_code_quality_run(workflow_id),
                latest.get("narrative", ""),
                latest.get("checksum_sha256", ""),
                pdf_file,
                workflow_id=workflow_id
            )
        if os.path.isfile(pdf_file):
            with open(pdf_file, "rb") as f:
                data = f.read()
            return Response(data, mimetype="application/pdf",
                            headers={"Content-Disposition": f"attachment; filename={key}.pdf"})
        return fail("NOT_FOUND", "PDF generation failed", 404)

    elif fmt == "html":
        html_file = os.path.abspath(base_file.replace(".md", ".html"))
        if os.path.isfile(html_file):
            with open(html_file, "r", encoding="utf-8") as f:
                content = f.read()
            return Response(content, mimetype="text/html",
                            headers={"Content-Disposition": f"attachment; filename={key}.html"})
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
            latest.get("checksum_sha256", ""),
            workflow_id=workflow_id
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
        md_file = os.path.abspath(base_file)
        if os.path.isfile(md_file):
            with open(md_file, "r", encoding="utf-8") as f:
                content = f.read()
            return Response(content, mimetype="text/markdown",
                            headers={"Content-Disposition": f"attachment; filename={key}.md"})
        return Response(latest.get("narrative") or "Evidence file not found", mimetype="text/markdown",
                        headers={"Content-Disposition": f"attachment; filename={key}.md"})


@approval_bp.route("/workflows/<workflow_id>/screenshots/<filename>", methods=["GET"])
def get_screenshot(workflow_id, filename):
    import os
    from flask import Response
    clean_fn = os.path.basename(filename)
    candidates = [
        os.path.join(os.getcwd(), "evidence_output", "screenshots", workflow_id, clean_fn),
        os.path.join(os.getcwd(), "evidence_output", "screenshots", "default", clean_fn),
        os.path.join("evidence_output", "screenshots", workflow_id, clean_fn),
        os.path.join("evidence_output", "screenshots", "default", clean_fn),
    ]
    for c in candidates:
        abs_c = os.path.abspath(c)
        if os.path.isfile(abs_c):
            with open(abs_c, "rb") as f:
                img_data = f.read()
            return Response(img_data, mimetype="image/png")
    return fail("NOT_FOUND", "Screenshot not found", 404)



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


