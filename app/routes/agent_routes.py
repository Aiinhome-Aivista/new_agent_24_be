# pyrefly: ignore [missing-import]
from flask import Blueprint
from app.errors.handlers import ok
from app.auth.decorators import require_auth, require_permission
from app.repositories.workflow_repo import list_agent_runs
from app.extensions.db import query

agent_bp = Blueprint("agents", __name__)

_AGENTS = [
    {
        "name": "orchestrator",
        "label": "TDD Orchestrator",
        "role": "State Machine Governor & Human Checkpoint Coordinator",
        "tier": "Workflow Engine",
        "model_or_tool": "State Machine Engine",
    },
    {
        "name": "requirement_analyzer",
        "label": "Requirement Analyzer",
        "role": "AC Scenario Decomposition & Ambiguity Detection",
        "tier": "LLM Reasoning",
        "model_or_tool": "Gemini 3.1 Flash-Lite",
    },
    {
        "name": "service_planner",
        "label": "Service Planner",
        "role": "API Contract & Service Dependency Synthesis",
        "tier": "LLM Reasoning",
        "model_or_tool": "Gemini 3.1 Flash-Lite",
    },
    {
        "name": "review_agent",
        "label": "Review Agent",
        "role": "Contract Gap & Missing Function Audit",
        "tier": "LLM Reasoning",
        "model_or_tool": "Gemini 3.1 Flash-Lite",
    },
    {
        "name": "test_generator",
        "label": "Test Generator",
        "role": "Traceable TDD Test Specification & Function Mapping",
        "tier": "LLM Code",
        "model_or_tool": "Gemini 3.1 Flash-Lite",
    },
    {
        "name": "code_generator",
        "label": "Code Generator",
        "role": "Compilable JUnit5 / PyTest Test Code Synthesis",
        "tier": "LLM Code",
        "model_or_tool": "Gemini 3.1 Flash-Lite",
    },
    {
        "name": "api_executor",
        "label": "API Executor",
        "role": "Deterministic HTTP & Postman Collection Runner",
        "tier": "Tool Adapter",
        "model_or_tool": "HttpRunner / Newman",
    },
    {
        "name": "code_validator",
        "label": "Code Validator",
        "role": "Static Quality & Security Rule Analysis",
        "tier": "Tool + LLM",
        "model_or_tool": "SonarQube / Checkstyle",
    },
    {
        "name": "evidence_generator",
        "label": "Evidence Generator",
        "role": "Audit Evidence Compilation & SHA-256 Checksum",
        "tier": "Doc Engine",
        "model_or_tool": "Markdown / HTML / SHA-256",
    },
    {
        "name": "alm_agent",
        "label": "ALM Agent",
        "role": "Idempotent External ALM Sync (Jira / Azure DevOps)",
        "tier": "ALM Adapter",
        "model_or_tool": "Jira / Azure DevOps API",
    },
]


@agent_bp.route("/agents", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def agents():
    # Attach latest run status, latency, task_type per agent
    latest = {}
    for row in query("""SELECT agent, status, task_type, latency_ms, created_at FROM agent_runs
                        ORDER BY created_at DESC LIMIT 300"""):
        latest.setdefault(row["agent"], row)
    enriched = [{**a, "last_run": latest.get(a["name"])} for a in _AGENTS]

    # Calculate overall stats
    total_runs = query("SELECT COUNT(*) AS c, AVG(latency_ms) AS avg_lat FROM agent_runs", fetchone=True) or {}
    return ok({
        "agents": enriched,
        "total_agents": len(enriched),
        "total_executions": total_runs.get("c", 0),
        "avg_latency_ms": round(float(total_runs.get("avg_lat") or 0), 1),
    })


@agent_bp.route("/agents/activity", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def activity():
    runs = list_agent_runs()
    return ok({"activity": runs})
