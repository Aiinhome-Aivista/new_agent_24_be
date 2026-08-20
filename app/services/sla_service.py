"""
SLA & Evaluation Metrics Engine.
Computes stage latencies vs target SLAs, requirement coverage %, quality gate compliance,
and token/cost observability for workflows.
"""
from app.extensions.db import query
from app.repositories.workflow_repo import get_run, list_agent_runs
from app.repositories.test_repo import list_test_cases, get_execution_run, get_code_quality_run

# Standard SLA Latency Targets (in milliseconds)
STAGE_SLA_TARGETS = {
    "requirement_analysis": {"target_ms": 8000, "label": "Requirement Analysis", "tier": "Agent Reasoning"},
    "service_planning": {"target_ms": 5000, "label": "Service Planning", "tier": "Agent Reasoning"},
    "test_generation": {"target_ms": 12000, "label": "Test Case & Code Generation", "tier": "Code LLM"},
    "api_execution": {"target_ms": 5000, "label": "API Test Execution", "tier": "Deterministic Tool"},
    "code_validation": {"target_ms": 5000, "label": "Code Quality Analysis", "tier": "Deterministic Tool"},
    "evidence_generation": {"target_ms": 5000, "label": "Evidence Generation & Seal", "tier": "Doc Engine"},
    "alm_attachment": {"target_ms": 3000, "label": "ALM Write-Back", "tier": "ALM Adapter"},
}

QUALITY_GATE_THRESHOLD = 85.0
REQUIREMENT_COVERAGE_TARGET = 90.0
API_PASS_RATE_TARGET = 80.0

# Gemini Flash pricing estimates ($ per 1M tokens)
INPUT_TOKEN_COST_PER_M = 0.075
OUTPUT_TOKEN_COST_PER_M = 0.30


def evaluate_workflow_sla(workflow_id):
    """
    Computes a comprehensive SLA and quality gate evaluation report for a workflow run.
    """
    run = get_run(workflow_id)
    if not run:
        return None

    agent_runs = list_agent_runs(workflow_id)
    test_cases = list_test_cases(workflow_id)
    exec_run = get_execution_run(workflow_id)
    cq_run = get_code_quality_run(workflow_id)

    state = run.get("state_json") or {}
    acs = state.get("acceptance_criteria") or []
    if not acs and run.get("story_id"):
        ac_rows = query("SELECT text FROM acceptance_criteria WHERE story_id=%s", (run["story_id"],))
        acs = [r["text"] for r in ac_rows]

    # 1. Stage Latency Metrics
    stage_metrics = []
    total_pipeline_ms = 0
    total_target_ms = 0
    any_sla_breached = False

    # Group agent runs by task_type/agent
    agent_latencies = {}
    for ar in agent_runs:
        key = ar.get("task_type") or ar.get("agent")
        latency = ar.get("latency_ms") or 0
        agent_latencies[key] = latency

    for stage_key, meta in STAGE_SLA_TARGETS.items():
        actual_ms = agent_latencies.get(stage_key)
        target_ms = meta["target_ms"]
        
        if actual_ms is not None:
            total_pipeline_ms += actual_ms
            total_target_ms += target_ms
            is_met = actual_ms <= target_ms
            if not is_met:
                any_sla_breached = True
            
            stage_metrics.append({
                "stage": stage_key,
                "label": meta["label"],
                "tier": meta["tier"],
                "target_ms": target_ms,
                "actual_ms": actual_ms,
                "delta_ms": actual_ms - target_ms,
                "status": "MET" if is_met else "BREACHED",
                "executed": True,
            })
        else:
            total_target_ms += target_ms
            stage_metrics.append({
                "stage": stage_key,
                "label": meta["label"],
                "tier": meta["tier"],
                "target_ms": target_ms,
                "actual_ms": 0,
                "delta_ms": 0,
                "status": "PENDING",
                "executed": False,
            })

    # 2. Requirement Coverage Metric
    total_acs = max(len(acs), 1)
    total_tests = len(test_cases)
    # Each AC is considered covered if at least 1 test case exists
    coverage_pct = min(100.0, round((total_tests / total_acs) * 100.0, 1)) if total_tests > 0 else 0.0
    coverage_sla_met = coverage_pct >= REQUIREMENT_COVERAGE_TARGET

    # 3. Quality Gate Metric
    cq_score = float(cq_run.get("score", 90.0)) if cq_run else 90.0
    cq_passed = cq_score >= QUALITY_GATE_THRESHOLD

    # 4. API Execution Metric
    api_pass_rate = 100.0
    if exec_run and exec_run.get("total", 0) > 0:
        api_pass_rate = round((exec_run.get("passed", 0) / exec_run["total"]) * 100.0, 1)

    # 5. Token & Cost Estimation
    # Heuristic estimation based on prompt size + code generation tokens
    estimated_prompt_tokens = 0
    estimated_completion_tokens = 0
    for ar in agent_runs:
        out_summary = ar.get("output_summary") or {}
        is_mock = out_summary.get("is_mock", False)
        if not is_mock:
            estimated_prompt_tokens += 1200
            estimated_completion_tokens += 850
        else:
            estimated_prompt_tokens += 300
            estimated_completion_tokens += 150

    estimated_cost_usd = round(
        (estimated_prompt_tokens / 1_000_000 * INPUT_TOKEN_COST_PER_M) +
        (estimated_completion_tokens / 1_000_000 * OUTPUT_TOKEN_COST_PER_M), 6
    )

    # Overall SLA Determination
    overall_status = "MET"
    if any_sla_breached or not cq_passed:
        overall_status = "BREACHED"
    elif run.get("status") in ("FAILED", "BLOCKED"):
        overall_status = "BREACHED"
    elif run.get("status") != "COMPLETED":
        overall_status = "IN_PROGRESS"

    return {
        "workflow_id": workflow_id,
        "workflow_status": run.get("status"),
        "current_stage": run.get("current_stage"),
        "overall_sla_status": overall_status,
        "total_actual_latency_ms": total_pipeline_ms,
        "total_target_latency_ms": total_target_ms,
        "stage_metrics": stage_metrics,
        "requirement_coverage": {
            "total_acceptance_criteria": len(acs),
            "generated_test_cases": total_tests,
            "coverage_percentage": coverage_pct,
            "target_percentage": REQUIREMENT_COVERAGE_TARGET,
            "status": "MET" if coverage_sla_met else "WARNING",
        },
        "quality_gate": {
            "score": cq_score,
            "threshold": QUALITY_GATE_THRESHOLD,
            "status": "PASS" if cq_passed else "FAIL",
            "issues_count": len(cq_run.get("issues", [])) if cq_run and isinstance(cq_run.get("issues"), list) else 0,
        },
        "api_execution_sla": {
            "pass_rate_percentage": api_pass_rate,
            "target_pass_rate": API_PASS_RATE_TARGET,
            "total_executed": exec_run.get("total", 0) if exec_run else 0,
            "total_passed": exec_run.get("passed", 0) if exec_run else 0,
            "status": "MET" if api_pass_rate >= API_PASS_RATE_TARGET else "BREACHED",
        },
        "token_observability": {
            "estimated_prompt_tokens": estimated_prompt_tokens,
            "estimated_completion_tokens": estimated_completion_tokens,
            "estimated_total_tokens": estimated_prompt_tokens + estimated_completion_tokens,
            "estimated_cost_usd": estimated_cost_usd,
            "currency": "USD",
        }
    }
