"""
TDD Test Evidence Orchestrator. Creates the plan, maintains workflow state, routes to
specialist agents, stops at human checkpoints, enforces guardrails, and persists every
transition. It never fabricates results, invents requirements, or writes to ALM without
approval.
"""
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
                state["status"] = STAGE_STATUS.get(stage, sm.WAITING_FOR_REVIEW)
                self._open_checkpoint(workflow_id, stage, state)
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

            # Mark as RUNNING and persist current stage
            state["status"] = sm.RUNNING
            self._persist(workflow_id, state)

            state = agent.run(workflow_id, state)
            self._persist(workflow_id, state)

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
