from flask import Blueprint
from app.errors.handlers import ok
from app.auth.decorators import require_auth, require_permission
from app.repositories.workflow_repo import list_agent_runs
from app.extensions.db import query

agent_bp = Blueprint("agents", __name__)

_AGENTS = [
    {"name": "orchestrator", "label": "TDD Orchestrator"},
    {"name": "requirement_analyzer", "label": "Requirement Analyzer"},
    {"name": "service_planner", "label": "Service Planner"},
    {"name": "test_generator", "label": "Test Generator"},
    {"name": "api_executor", "label": "API Executor"},
    {"name": "code_validator", "label": "Code Validator"},
    {"name": "evidence_generator", "label": "Evidence Generator"},
    {"name": "alm_agent", "label": "ALM Agent"},
]


@agent_bp.route("/agents", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def agents():
    # Attach latest run status per agent.
    latest = {}
    for row in query("""SELECT agent, status, created_at FROM agent_runs
                        ORDER BY created_at DESC LIMIT 200"""):
        latest.setdefault(row["agent"], row)
    enriched = [{**a, "last_run": latest.get(a["name"])} for a in _AGENTS]
    return ok({"agents": enriched})


@agent_bp.route("/agents/activity", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def activity():
    return ok({"activity": list_agent_runs()})
