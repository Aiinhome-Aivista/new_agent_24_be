"""
Jira Integration Routes — Test connectivity, list stories/features, and fetch story details.
"""
from flask import Blueprint, request, g
from app.errors.handlers import ok, fail
from app.auth.decorators import require_auth
from app.tools.jira.client import JiraClient
from app.audit.audit_log import record as audit

jira_bp = Blueprint("jira", __name__)


@jira_bp.route("/jira/status", methods=["GET"])
@require_auth
def jira_status():
    """Returns the Jira connection status and configured user profile."""
    client = JiraClient()
    if not client.is_configured():
        return ok({
            "configured": False,
            "connected": False,
            "message": "Jira integration is not fully configured (set JIRA_BASE_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN in .env)."
        })
    status = client.test_connection()
    return ok({
        "configured": True,
        **status
    })


@jira_bp.route("/jira/stories", methods=["GET"])
@require_auth
def jira_stories():
    """Lists recent stories, features, and tasks from Jira."""
    project_key = request.args.get("project")
    max_results = int(request.args.get("max_results", 30))
    client = JiraClient()
    
    if not client.is_configured():
        return ok({"issues": [], "configured": False, "message": "Jira not configured"})

    try:
        issues = client.list_issues(project_key=project_key, max_results=max_results)
        return ok({"issues": issues, "configured": True, "count": len(issues)})
    except Exception as e:
        return fail("JIRA_ERROR", f"Failed to list Jira stories: {str(e)}", 500)


@jira_bp.route("/jira/fetch-story", methods=["POST"])
@require_auth
def jira_fetch_story():
    """
    Fetches a specific story/feature from Jira by key (e.g. 'SCRUM-40'),
    converts ADF description to markdown, and extracts structured Acceptance Criteria.
    """
    body = request.get_json(silent=True) or {}
    issue_key = body.get("issue_key", "").strip()

    if not issue_key:
        return fail("VALIDATION_ERROR", "Issue key is required (e.g. 'SCRUM-40').")

    client = JiraClient()
    if not client.is_configured():
        return fail("CONFIGURATION_ERROR", "Jira integration credentials are not configured in the backend .env file.", 400)

    try:
        story = client.get_issue(issue_key)
        audit(
            "jira_story_fetch",
            user_id=getattr(g, "user_id", None),
            status="SUCCESS",
            metadata={"issue_key": issue_key, "title": story.get("title"), "acs_count": len(story.get("acceptance_criteria", []))}
        )
        return ok(story, f"Successfully fetched story '{issue_key}' from Jira.")
    except ValueError as ve:
        return fail("NOT_FOUND", str(ve), 404)
    except Exception as e:
        return fail("JIRA_FETCH_FAILED", f"Could not fetch story '{issue_key}' from Jira: {str(e)}", 500)


@jira_bp.route("/jira/sync-evidence", methods=["POST"])
@require_auth
def jira_sync_evidence():
    """
    Syncs verification evidence report to the specified Jira Story / Issue:
    1. Uploads the signed .docx package (with embedded screenshots) as an attachment.
    2. Posts a structured test summary report comment (with pass rate, telemetry, and criteria breakdown).
    """
    import os
    from app.routes.api_execution_routes import _AUTONOMOUS_EVIDENCE_STORE
    from app.tools.document_generator.docx_generator import generate_docx_evidence

    body = request.get_json(silent=True) or {}
    issue_key = (body.get("issue_key") or "").strip().upper()
    evidence_key = (body.get("evidence_key") or "").strip()
    evidence_data = body.get("evidence_data") or _AUTONOMOUS_EVIDENCE_STORE.get(evidence_key) or {}
    comment_note = body.get("comment_note") or "Autonomous test verification completed and authorized."
    approver_name = body.get("approver_name") or "Authorized Lead QA"

    if not issue_key:
        return fail("VALIDATION_ERROR", "Jira Story / Issue key is required (e.g. 'SCRUM-40').")

    if not evidence_data and not evidence_key:
        return fail("VALIDATION_ERROR", "Evidence data or valid evidence_key is required.")

    client = JiraClient()
    if not client.is_configured():
        return fail("CONFIGURATION_ERROR", "Jira integration credentials are not configured in backend .env.", 400)

    # Locate or generate the .docx package
    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "evidence_output"))
    docx_path = os.path.join(out_dir, f"{evidence_key}.docx")

    if not os.path.exists(docx_path):
        workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        ws_path = os.path.join(workspace_root, f"{evidence_key}.docx")
        if os.path.exists(ws_path):
            docx_path = ws_path
        elif evidence_data:
            docx_path = generate_docx_evidence(evidence_data, out_dir=out_dir)

    try:
        sync_result = client.sync_evidence_package(
            issue_key=issue_key,
            evidence_data=evidence_data,
            docx_path=docx_path if os.path.exists(docx_path) else None,
            approval_comment=comment_note,
            approver_name=approver_name,
        )

        # Update evidence store record
        if evidence_key and evidence_key in _AUTONOMOUS_EVIDENCE_STORE:
            _AUTONOMOUS_EVIDENCE_STORE[evidence_key]["jira_synced"] = True
            _AUTONOMOUS_EVIDENCE_STORE[evidence_key]["jira_sync_result"] = sync_result

        audit(
            "jira_evidence_sync",
            user_id=getattr(g, "user_id", None),
            status="SUCCESS",
            metadata={
                "issue_key": issue_key,
                "evidence_key": evidence_key,
                "approver": approver_name,
                "comment_id": sync_result.get("comment_id"),
            }
        )

        return ok(sync_result, f"Verification evidence package successfully saved to Jira Story [{issue_key}].")
    except Exception as e:
        return fail("JIRA_SYNC_FAILED", f"Failed to save evidence to Jira Story '{issue_key}': {str(e)}", 500)
