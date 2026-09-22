"""
TDD Test Evidence Orchestrator. Creates the plan, maintains workflow state, routes to
specialist agents, stops at human checkpoints, enforces guardrails, and persists every
transition. It never fabricates results, invents requirements, or writes to ALM without
approval.

LangGraph Integration:
    When langgraph is installed, workflow execution is routed through the compiled
    LangGraph StateGraph (app/workflows/langgraph_workflow.py). This provides proper
    state management, conditional edge routing, and graph visualization.
    Falls back transparently to the existing while-loop if langgraph is unavailable.

Execution Trace:
    Every pipeline run now generates a structured execution trace (execution_trace.json)
    that records stage timing, inputs, outputs, status, artifacts, and metric provenance.
    The trace is an OBSERVER — it does not replace or alter the existing workflow.
"""
import os
from app.agents.requirement_analyzer.agent import RequirementAnalyzerAgent
from app.agents.service_planner.agent import ServicePlannerAgent
from app.agents.test_generator.agent import TestGeneratorAgent
from app.agents.code_generator.agent import CodeGeneratorAgent
from app.agents.api_executor.agent import ApiExecutorAgent
from app.agents.code_validator.agent import CodeValidatorAgent
from app.agents.evidence_generator.agent import EvidenceGeneratorAgent
from app.agents.alm_agent.agent import AlmAgent
from app.agents.review_agent.agent import ReviewAgent
from app.repositories.workflow_repo import update_run
from app.repositories.evidence_repo import create_approval
from app.audit.audit_log import record as audit
from app.workflows import state_machine as sm
from app.observability.execution_trace import (
    ExecutionTrace, TraceStatus, ArtifactRef,
    SM_TO_TRACE_STAGE, STAGE_HUMAN_REVIEW,
    STAGE_UNIT_TEST_EXECUTION, STAGE_CODE_COVERAGE,
    determine_stage_status, extract_stage_input_summary,
    extract_stage_output_summary,
)

# Attempt to load LangGraph workflow at import time (non-blocking)
_langgraph_workflow = None
try:
    from app.workflows.langgraph_workflow import get_workflow_graph
    _langgraph_workflow = get_workflow_graph()
except Exception as _lg_err:
    print(f"[Orchestrator] LangGraph not available: {_lg_err}. Using built-in state machine loop.")
    _langgraph_workflow = None


# Stage -> agent (stages not present are advanced directly, e.g. TEST_PLANNING folds into generation)
STAGE_AGENTS = {
    sm.REQUIREMENT_ANALYSIS: RequirementAnalyzerAgent(),
    sm.SERVICE_PLANNING: ServicePlannerAgent(),
    sm.TEST_PLANNING: ReviewAgent(),
    sm.TEST_GENERATION: TestGeneratorAgent(),
    sm.CODE_GENERATION: CodeGeneratorAgent(),
    sm.API_EXECUTION: ApiExecutorAgent(),
    sm.CODE_VALIDATION: CodeValidatorAgent(),
    sm.EVIDENCE_GENERATION: EvidenceGeneratorAgent(),
    sm.ALM_ATTACHMENT: AlmAgent(),
}

# Which running status corresponds to each stage (for the execution monitor).
STAGE_STATUS = {
    sm.REQUIREMENT_ANALYSIS: sm.RUNNING,
    sm.SERVICE_PLANNING: sm.RUNNING,
    sm.TEST_PLANNING: sm.RUNNING,
    sm.TEST_PLAN_REVIEW: sm.WAITING_FOR_REVIEW,
    sm.TEST_GENERATION: sm.RUNNING,
    sm.TEST_REVIEW: sm.WAITING_FOR_REVIEW,
    sm.CODE_GENERATION: sm.RUNNING,
    sm.API_EXECUTION: sm.EXECUTING,
    sm.CODE_VALIDATION: sm.VALIDATING,
    sm.POSTMAN_COLLECTION_REQUIRED: sm.WAITING_FOR_REVIEW,
    sm.EVIDENCE_GENERATION: sm.GENERATING_EVIDENCE,
    sm.ALM_APPROVAL: sm.WAITING_FOR_APPROVAL,
    sm.ALM_ATTACHMENT: sm.RUNNING,
    sm.DONE: sm.COMPLETED,
}


class Orchestrator:
    name = "orchestrator"

    def advance(self, workflow_id, state):
        """
        Advance the workflow from its current stage.

        Priority:
        1. LangGraph StateGraph (if langgraph installed and graph compiled)
        2. Built-in while-loop state machine (always-available fallback)
        """
        # ── LangGraph path ────────────────────────────────────────────────
        graph = _langgraph_workflow
        if graph is not None:
            return self._advance_via_langgraph(workflow_id, state, graph)

        # ── Fallback: built-in while-loop ─────────────────────────────────
        return self._advance_via_loop(workflow_id, state)

    def _advance_via_langgraph(self, workflow_id, state, graph):
        """
        Execute workflow stages using the compiled LangGraph StateGraph.

        LangGraph graph.invoke() always runs from the fixed entry_point
        (set_entry_point = requirement_analysis). Without a checkpointer
        backend, it CANNOT resume mid-graph — it always restarts from the top.

        Strategy:
        - Fresh start (CREATED / REQUIREMENT_ANALYSIS): use LangGraph — the
          graph runs from the beginning and routes correctly to checkpoints.
        - Mid-pipeline resumption (any other stage): use the while-loop, which
          can start from any stage. LangGraph's compiled graph is still the
          authoritative node/edge definition; the loop just drives execution
          without the graph runner.
        """
        stage = state.get("current_stage", sm.CREATED)
        is_fresh_start = stage in (sm.CREATED, sm.REQUIREMENT_ANALYSIS)

        if not is_fresh_start:
            # Mid-pipeline resumption: fall back to the while-loop which can
            # start from any stage.
            print(f"[ORCHESTRATOR][LangGraph] Mid-pipeline resume at {stage} — using loop.")
            return self._advance_via_loop(workflow_id, state)

        print(f"[ORCHESTRATOR][LangGraph] Fresh start — running graph from requirement_analysis.")
        try:
            state["workflow_id"] = workflow_id
            result_state = graph.invoke(state)
            self._persist(workflow_id, result_state)
            return result_state
        except Exception as e:
            print(f"[ORCHESTRATOR][LangGraph] Error during graph execution: {e}. Falling back to loop.")
            return self._advance_via_loop(workflow_id, state)

    def _advance_via_loop(self, workflow_id, state):
        """Original while-loop state machine — always-available fallback.
        Now instrumented with ExecutionTrace for full auditability."""
        # ── Initialize Execution Trace ────────────────────────────────────
        trace = self._get_or_create_trace(workflow_id, state)
        state["execution_trace"] = trace.serialize()  # initial snapshot

        guard = 0
        while guard < 30:
            guard += 1
            stage = state.get("current_stage", sm.CREATED)
            print(f"[ORCHESTRATOR] Advancing workflow {workflow_id[:8]}... Stage: {stage}")

            # Terminal / exception
            if stage == sm.DONE or state.get("status") in (sm.COMPLETED, sm.FAILED, sm.CANCELLED):
                break

            # Human checkpoint: create a pending approval and stop.
            if stage in sm.HUMAN_CHECKPOINTS:
                print(f"[ORCHESTRATOR] Halting at human checkpoint: {stage}")
                # Record human review stage in trace
                trace_stage_name = SM_TO_TRACE_STAGE.get(stage, STAGE_HUMAN_REVIEW)
                ht = trace.start_stage(trace_stage_name,
                    input_summary={"checkpoint": stage, "review_required": True})
                ht.complete(status=TraceStatus.AWAITING_HUMAN_APPROVAL,
                    output_summary={"review_status": "PENDING", "checkpoint": stage})

                state["status"] = STAGE_STATUS.get(stage, sm.WAITING_FOR_REVIEW)
                self._open_checkpoint(workflow_id, stage, state)
                state["execution_trace"] = trace.serialize()
                self._persist(workflow_id, state)
                break

            agent = STAGE_AGENTS.get(stage)
            if not agent:
                # Direct transition for stages without dedicated agents
                state["current_stage"] = sm.next_stage(stage)
                self._persist(workflow_id, state)
                continue

            print(f"\n{'='*75}")
            print(f"[ORCHESTRATOR] >>> Executing Stage: {stage} (Workflow: {workflow_id[:8]})")
            print(f"{'='*75}")

            # ── Start trace for this stage ────────────────────────────────
            trace_stage_name = SM_TO_TRACE_STAGE.get(stage, stage.lower())
            stage_trace = trace.start_stage(
                trace_stage_name,
                input_summary=extract_stage_input_summary(trace_stage_name, state),
            )
            stage_trace.add_tool_call(agent.name)

            # Mark as RUNNING and persist current stage
            state["status"] = sm.RUNNING
            self._persist(workflow_id, state)

            state = agent.run(workflow_id, state)
            self._persist(workflow_id, state)

            # ── Complete trace for this stage ─────────────────────────────
            trace_status = determine_stage_status(trace_stage_name, state)
            trace.complete_stage(
                stage_trace,
                status=trace_status,
                output_summary=extract_stage_output_summary(trace_stage_name, state),
            )

            # For CODE_VALIDATION stage, also record coverage as a separate trace stage
            if stage == sm.CODE_VALIDATION:
                self._record_coverage_trace(trace, state)

            if state.get("status") in sm.EXCEPTION:
                print(f"[ORCHESTRATOR] Stage {stage} encountered an exception. Status: {state.get('status')}")
                break

            # STRICT GATE: Halt before EVIDENCE_GENERATION if no Postman collection is provided
            next_target_stage = state.get("current_stage")
            if next_target_stage == sm.EVIDENCE_GENERATION or stage == sm.CODE_VALIDATION:
                if not self._has_postman_collection(workflow_id, state):
                    print(f"[ORCHESTRATOR] [GATE] No Postman collection provided! Halting before EVIDENCE_GENERATION.")
                    state["current_stage"] = sm.POSTMAN_COLLECTION_REQUIRED
                    state["status"] = sm.WAITING_FOR_REVIEW
                    state["postman_required"] = True
                    self._open_checkpoint(workflow_id, sm.POSTMAN_COLLECTION_REQUIRED, state)
                    self._persist(workflow_id, state)
                    break

        # ── Finalize and persist trace ────────────────────────────────────
        self._finalize_trace(trace, state)
        state["execution_trace"] = trace.serialize()
        self._persist(workflow_id, state)
        return state

    def resume(self, workflow_id, state, checkpoint):
        """Called after a human approves a checkpoint."""
        state["current_stage"] = sm.next_stage(checkpoint)
        if state.get("status") in (sm.WAITING_FOR_REVIEW, sm.WAITING_FOR_APPROVAL, sm.BLOCKED):
            state["status"] = sm.RUNNING
        return self.advance(workflow_id, state)

    def _has_postman_collection(self, workflow_id, state):
        """Checks if a Postman collection has been provided for this workflow or project."""
        if state.get("postman_collection") or state.get("collection_json") or state.get("collection_path"):
            return True

        contracts = state.get("api_contracts", [])
        if contracts and any(c.get("source") in ("POSTMAN", "POSTMAN_COLLECTION") or c.get("from_collection") for c in contracts):
            return True

        project_id = state.get("project_id") or (state.get("project") or {}).get("id") or (state.get("story") or {}).get("project_id")
        if not project_id:
            story = state.get("story", {})
            if story.get("uuid"):
                try:
                    from app.repositories.project_repo import get_story
                    st = get_story(story["uuid"])
                    if st:
                        project_id = st.get("project_id")
                except Exception:
                    pass

        if project_id:
            try:
                from app.extensions.db import query
                doc = query("""
                    SELECT id FROM knowledge_documents
                    WHERE project_id = %s AND (doc_type IN ('postman_collection', 'postman') OR (doc_type = 'api_contract' AND title LIKE '%.json'))
                    LIMIT 1
                """, (project_id,), fetchone=True)
                if doc:
                    return True
            except Exception:
                pass

        return False

    def _open_checkpoint(self, workflow_id, stage, state):
        import uuid
        stage_to_approval = {
            sm.TEST_PLAN_REVIEW: "TEST_PLAN_REVIEW",
            sm.TEST_REVIEW: "TEST_REVIEW",
            sm.POSTMAN_COLLECTION_REQUIRED: "POSTMAN_COLLECTION_REQUIRED",
            sm.ALM_APPROVAL: "ALM_APPROVAL",
        }
        create_approval(str(uuid.uuid4()), workflow_id, stage_to_approval.get(stage, stage))
        state["status"] = STAGE_STATUS.get(stage, sm.WAITING_FOR_REVIEW)
        audit("workflow_transition", workflow_id=workflow_id, agent=self.name,
              status=state["status"], metadata={"checkpoint": stage})

    def _persist(self, workflow_id, state):
        stage = state.get("current_stage", sm.CREATED)
        status = state.get("status") or STAGE_STATUS.get(stage, sm.RUNNING)
        errors = state.get("errors", [])
        update_run(workflow_id, status, stage, state,
                   current_agent=self.name,
                   error_code="AGENT_ERROR" if errors and status in sm.EXCEPTION else None,
                   error_message=(errors[-1]["message"] if errors and status in sm.EXCEPTION else None))
        audit("workflow_transition", workflow_id=workflow_id, agent=self.name, status=status,
              metadata={"stage": stage})

    # ── Execution Trace Helpers ───────────────────────────────────────────

    def _get_or_create_trace(self, workflow_id, state):
        """Create or resume an ExecutionTrace for this workflow run."""
        # Reuse existing evidence key as run_id if available
        evidence = state.get("evidence", {})
        run_id = evidence.get("evidence_key")
        if not run_id:
            import uuid as _uuid
            run_id = f"EVID-{_uuid.uuid4().hex[:8]}"
        return ExecutionTrace(run_id=run_id)

    def _record_coverage_trace(self, trace, state):
        """Record a dedicated coverage trace stage from CODE_VALIDATION results."""
        rc = state.get("real_code_coverage", {})
        cov_stage = trace.start_stage(
            STAGE_CODE_COVERAGE,
            input_summary={
                "coverage_tool": "pytest-cov / coverage.py",
                "generated_test_path": (state.get("code_generation") or {}).get("files_written", [{}])[0].get("file_path", "N/A") if (state.get("code_generation") or {}).get("files_written") else "N/A",
                "workspace_path": state.get("workspace_path", "N/A"),
            },
        )
        cov_stage.add_tool_call("coverage.py")

        if rc.get("is_mock"):
            cov_stage.complete(status=TraceStatus.INCONCLUSIVE,
                output_summary={"reason": rc.get("reason", "Coverage not executed")})
        else:
            cov_stage.complete(status=TraceStatus.PASS,
                output_summary={
                    "line_coverage_pct": rc.get("line_coverage_pct"),
                    "branch_coverage_pct": rc.get("branch_coverage_pct"),
                    "num_statements": rc.get("num_statements", 0),
                    "num_missing": rc.get("num_missing", 0),
                    "scoped_source_files": rc.get("scoped_source_files", []),
                })

        # Add coverage provenance records
        if not rc.get("is_mock"):
            trace.add_provenance(
                metric_name="Scoped Line Coverage",
                source_tool="coverage.py JSON",
                value=rc.get("line_coverage_pct"),
                stage_id=cov_stage.stage_id,
            )
            trace.add_provenance(
                metric_name="Scoped Branch Coverage",
                source_tool="coverage.py JSON",
                value=rc.get("branch_coverage_pct"),
                stage_id=cov_stage.stage_id,
            )

    def _finalize_trace(self, trace, state):
        """Add provenance records and save trace artifact after run completes."""
        # ── Provenance: Requirement Traceability ──────────────────────────
        mapping = state.get("ac_api_code_mapping", [])
        acs = state.get("acceptance_criteria", [])
        trace.add_provenance(
            metric_name="Requirement Traceability",
            source_tool="TraceabilityMapper",
            value=f"{len(mapping)}/{len(acs)}",
        )

        # ── Provenance: User Story Unit Test Pass Rate ────────────────────
        ut = state.get("unit_test_execution", {})
        if ut.get("executed") and not ut.get("is_mock"):
            trace.add_provenance(
                metric_name="User Story Unit Test Pass Rate",
                source_tool="pytest execution",
                value=f"{ut.get('passed_tests', 0)}/{ut.get('total_tests', 0)}",
            )

        # ── Provenance: Real API Pass Rate ────────────────────────────────
        exec_data = state.get("execution", {})
        if exec_data and not exec_data.get("is_mock"):
            trace.add_provenance(
                metric_name="Real API Pass Rate",
                source_tool="HttpRunner / API execution telemetry",
                value=f"{exec_data.get('passed', 0)}/{exec_data.get('total', 0)}",
            )

        # ── Save trace to evidence_output ─────────────────────────────────
        try:
            out_dir = os.path.abspath(os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "evidence_output"))
            trace_path = trace.save_to_file(out_dir)
            trace.add_global_artifact(ArtifactRef(
                artifact_type="execution_trace",
                path=trace_path,
                description="Full execution trace JSON",
            ))
            print(f"[ORCHESTRATOR] Execution trace saved to: {trace_path}")
        except Exception as e:
            print(f"[ORCHESTRATOR] Warning: could not save execution trace: {e}")
