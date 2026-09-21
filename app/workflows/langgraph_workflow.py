"""
LangGraph Workflow Orchestration.

Wraps the existing agent swarm as LangGraph nodes in a StateGraph.
The existing agent logic is PRESERVED — LangGraph provides the framework
for state management, conditional routing, and workflow visualization.

Architecture:
    WorkflowState (TypedDict)
        ↓
    LangGraph StateGraph
        ↓
    Nodes: each pipeline stage = one node
        ↓
    Conditional edges: route to human checkpoint or next stage
        ↓
    Graph compiled and invoked from Orchestrator

Fallback:
    If langgraph is not available, the existing Orchestrator while-loop
    continues to function unchanged (zero breaking changes).
"""
from typing import Any, Dict, Optional
from typing_extensions import TypedDict

try:
    # pyrefly: ignore [missing-import]
    from langgraph.graph import StateGraph, END
    # pyrefly: ignore [missing-import]
    from langgraph.graph.state import CompiledStateGraph
    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False
    StateGraph = None
    END = "__end__"
    CompiledStateGraph = None


# ─────────────────────────────────────────────────────────────────────────────
# Shared State definition
# ─────────────────────────────────────────────────────────────────────────────

class WorkflowState(TypedDict, total=False):
    """
    Canonical state dictionary passed between all LangGraph nodes.
    Corresponds 1:1 with the state dict already used by every existing agent.
    Using total=False so all keys are optional (agents add keys incrementally).
    """
    # Identity
    workflow_id: str
    project_id: Optional[str]
    story_uuid: Optional[str]

    # Core workflow tracking
    current_stage: str
    status: str
    errors: list

    # Domain objects
    project: Dict[str, Any]
    story: Dict[str, Any]
    acceptance_criteria: list
    api_contracts: list
    postman_collection: Optional[Dict[str, Any]]
    collection_path: Optional[str]
    workspace_path: Optional[str]
    target_host: Optional[str]

    # Agent outputs
    scenarios: Optional[Dict[str, Any]]
    service_plan: Optional[Dict[str, Any]]
    generated_tests: list
    code_generation: Optional[Dict[str, Any]]
    execution: Optional[Dict[str, Any]]
    unit_test_execution: Optional[Dict[str, Any]]
    real_code_coverage: Optional[Dict[str, Any]]
    code_quality: Optional[Dict[str, Any]]
    coverage_matrix: list
    coverage_report: Optional[Dict[str, Any]]
    evidence: Optional[Dict[str, Any]]
    autonomous_evidence: Optional[Dict[str, Any]]
    alm: Optional[Dict[str, Any]]

    # Flags
    postman_required: Optional[bool]
    clarification_required: Optional[bool]


# ─────────────────────────────────────────────────────────────────────────────
# Node Wrappers — each node calls the existing agent and returns updated state
# ─────────────────────────────────────────────────────────────────────────────

def _make_agent_node(agent_instance, stage_name: str):
    """
    Factory that creates a LangGraph node function wrapping an existing agent.
    The node calls agent.run(workflow_id, state) exactly as the orchestrator does.
    """
    def node_fn(state: WorkflowState) -> WorkflowState:
        workflow_id = state.get("workflow_id", "")
        print(f"[LangGraph] Node [{stage_name}] — workflow {str(workflow_id)[:8]}")
        try:
            updated = agent_instance.run(workflow_id, dict(state))
            return updated
        except Exception as e:
            print(f"[LangGraph] Node [{stage_name}] raised exception: {e}")
            state = dict(state)
            state.setdefault("errors", []).append({"agent": stage_name, "message": str(e)})
            state["status"] = "FAILED"
            return state
    node_fn.__name__ = f"node_{stage_name.lower()}"
    return node_fn


def _persist_and_checkpoint(stage: str):
    """
    Returns a node function that persists state at a human checkpoint and halts.
    """
    def node_fn(state: WorkflowState) -> WorkflowState:
        from app.workflows.state_machine import WAITING_FOR_REVIEW, WAITING_FOR_APPROVAL
        from app.repositories.workflow_repo import update_run
        from app.repositories.evidence_repo import create_approval
        import uuid as _uuid

        workflow_id = state.get("workflow_id", "")
        checkpoint_status = WAITING_FOR_APPROVAL if "ALM" in stage else WAITING_FOR_REVIEW

        state = dict(state)
        state["status"] = checkpoint_status
        state["current_stage"] = stage

        # Create pending approval record
        try:
            create_approval(str(_uuid.uuid4()), workflow_id, stage)
        except Exception:
            pass

        # Persist
        try:
            update_run(workflow_id, checkpoint_status, stage, state)
        except Exception:
            pass

        print(f"[LangGraph] ⏸ Human checkpoint reached: {stage}")
        return state
    node_fn.__name__ = f"checkpoint_{stage.lower()}"
    return node_fn


# ─────────────────────────────────────────────────────────────────────────────
# Routing functions (conditional edges)
# ─────────────────────────────────────────────────────────────────────────────

def route_after_stage(state: WorkflowState) -> str:
    """
    Universal routing function called after each agent node.
    Returns the name of the next node to execute.
    """
    from app.workflows import state_machine as sm

    status = state.get("status", "")
    stage = state.get("current_stage", "")

    # Terminal / exception states → end the graph
    if stage == sm.DONE or status in (sm.COMPLETED, sm.FAILED, sm.CANCELLED, sm.BLOCKED):
        return END

    # Human checkpoints → route to checkpoint node (halts there)
    if stage in sm.HUMAN_CHECKPOINTS:
        return f"checkpoint_{stage.lower()}"

    # POSTMAN_COLLECTION_REQUIRED special checkpoint
    if stage == sm.POSTMAN_COLLECTION_REQUIRED:
        return "checkpoint_postman_collection_required"

    # Map the NEXT stage (set by the just-executed agent) to the node to run
    # Each agent sets current_stage = <next stage> before returning.
    stage_to_node = {
        sm.SERVICE_PLANNING: "service_planning",
        sm.TEST_PLANNING: "test_planning",
        sm.TEST_GENERATION: "test_generation",
        sm.TEST_REVIEW: "checkpoint_test_review",
        sm.CODE_GENERATION: "code_generation",
        sm.API_EXECUTION: "api_execution",
        sm.CODE_VALIDATION: "code_validation",
        sm.EVIDENCE_GENERATION: "evidence_generation",
        sm.ALM_APPROVAL: "checkpoint_alm_approval",
        sm.ALM_ATTACHMENT: "alm_attachment",
    }
    return stage_to_node.get(stage, END)


def route_after_code_validation(state: WorkflowState) -> str:
    """
    After code validation, check whether Postman collection is present.
    If not → POSTMAN_COLLECTION_REQUIRED checkpoint.
    If yes → EVIDENCE_GENERATION.
    """
    from app.workflows import state_machine as sm

    if state.get("postman_required"):
        return "checkpoint_postman_collection_required"

    stage = state.get("current_stage", "")
    if stage == sm.POSTMAN_COLLECTION_REQUIRED:
        return "checkpoint_postman_collection_required"

    return "evidence_generation"


# ─────────────────────────────────────────────────────────────────────────────
# Graph builder
# ─────────────────────────────────────────────────────────────────────────────

def build_workflow_graph() -> Optional["CompiledStateGraph"]:
    """
    Build and compile the LangGraph StateGraph for the Agent 24 workflow.

    Returns None if langgraph is not installed (caller falls back to while-loop).
    """
    if not HAS_LANGGRAPH:
        print("[LangGraph] langgraph not installed — using fallback orchestrator loop.")
        return None

    # Import existing agent instances (lazy to avoid circular imports at module level)
    from app.agents.requirement_analyzer.agent import RequirementAnalyzerAgent
    from app.agents.service_planner.agent import ServicePlannerAgent
    from app.agents.test_generator.agent import TestGeneratorAgent
    from app.agents.code_generator.agent import CodeGeneratorAgent
    from app.agents.api_executor.agent import ApiExecutorAgent
    from app.agents.code_validator.agent import CodeValidatorAgent
    from app.agents.evidence_generator.agent import EvidenceGeneratorAgent
    from app.agents.alm_agent.agent import AlmAgent
    from app.agents.review_agent.agent import ReviewAgent
    from app.workflows import state_machine as sm

    # Instantiate agents
    agents = {
        "requirement_analysis": RequirementAnalyzerAgent(),
        "service_planning": ServicePlannerAgent(),
        "test_planning": ReviewAgent(),
        "test_generation": TestGeneratorAgent(),
        "code_generation": CodeGeneratorAgent(),
        "api_execution": ApiExecutorAgent(),
        "code_validation": CodeValidatorAgent(),
        "evidence_generation": EvidenceGeneratorAgent(),
        "alm_attachment": AlmAgent(),
    }

    graph = StateGraph(WorkflowState)

    # ── Add agent nodes ────────────────────────────────────────────────────
    for node_name, agent in agents.items():
        graph.add_node(node_name, _make_agent_node(agent, node_name.upper()))

    # ── Add human checkpoint nodes (halt nodes) ────────────────────────────
    for chk in (sm.TEST_PLAN_REVIEW, sm.TEST_REVIEW, sm.ALM_APPROVAL, sm.POSTMAN_COLLECTION_REQUIRED):
        node_name = f"checkpoint_{chk.lower()}"
        graph.add_node(node_name, _persist_and_checkpoint(chk))

    # ── Set entry point ────────────────────────────────────────────────────
    graph.set_entry_point("requirement_analysis")

    # ── Add edges: agent → routing → next ─────────────────────────────────
    graph.add_conditional_edges("requirement_analysis", route_after_stage,
        {"service_planning": "service_planning", END: END,
         "checkpoint_test_plan_review": "checkpoint_test_plan_review"})

    graph.add_conditional_edges("service_planning", route_after_stage,
        {"test_planning": "test_planning", END: END})

    graph.add_conditional_edges("test_planning", route_after_stage,
        {"checkpoint_test_plan_review": "checkpoint_test_plan_review",
         "test_generation": "test_generation", END: END})

    graph.add_edge("checkpoint_test_plan_review", END)

    graph.add_conditional_edges("test_generation", route_after_stage,
        {"checkpoint_test_review": "checkpoint_test_review", END: END})

    graph.add_edge("checkpoint_test_review", END)

    graph.add_conditional_edges("code_generation", route_after_stage,
        {"api_execution": "api_execution", END: END})

    graph.add_conditional_edges("api_execution", route_after_stage,
        {"code_validation": "code_validation", END: END})

    # After code_validation: check Postman gate
    graph.add_conditional_edges("code_validation", route_after_code_validation,
        {"evidence_generation": "evidence_generation",
         "checkpoint_postman_collection_required": "checkpoint_postman_collection_required",
         END: END})

    graph.add_edge("checkpoint_postman_collection_required", END)

    graph.add_conditional_edges("evidence_generation", route_after_stage,
        {"checkpoint_alm_approval": "checkpoint_alm_approval", END: END})

    graph.add_edge("checkpoint_alm_approval", END)

    graph.add_conditional_edges("alm_attachment", route_after_stage,
        {END: END})

    compiled = graph.compile()
    print("[LangGraph] Workflow graph compiled successfully.")
    return compiled


# ─────────────────────────────────────────────────────────────────────────────
# Graph singleton
# ─────────────────────────────────────────────────────────────────────────────
_compiled_graph: Optional["CompiledStateGraph"] = None
_graph_build_attempted = False


def get_workflow_graph() -> Optional["CompiledStateGraph"]:
    """Return the compiled LangGraph workflow, building it on first call."""
    global _compiled_graph, _graph_build_attempted
    if not _graph_build_attempted:
        _graph_build_attempted = True
        try:
            _compiled_graph = build_workflow_graph()
        except Exception as e:
            print(f"[LangGraph] Failed to build graph: {e}. Falling back to orchestrator loop.")
            _compiled_graph = None
    return _compiled_graph
