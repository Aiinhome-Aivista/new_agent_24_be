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
