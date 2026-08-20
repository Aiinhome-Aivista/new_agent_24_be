"""
TDD Test Evidence Orchestrator. Creates the plan, maintains workflow state, routes to
specialist agents, stops at human checkpoints, enforces guardrails, and persists every
transition. It never fabricates results, invents requirements, or writes to ALM without
approval.
"""
from app.agents.requirement_analyzer.agent import RequirementAnalyzerAgent
from app.agents.service_planner.agent import ServicePlannerAgent
from app.agents.test_generator.agent import TestGeneratorAgent
from app.agents.api_executor.agent import ApiExecutorAgent
from app.agents.code_validator.agent import CodeValidatorAgent
from app.agents.evidence_generator.agent import EvidenceGeneratorAgent
from app.agents.alm_agent.agent import AlmAgent
from app.repositories.workflow_repo import update_run
from app.repositories.evidence_repo import create_approval
from app.audit.audit_log import record as audit
from app.workflows import state_machine as sm

# Stage -> agent (stages not present are advanced directly, e.g. TEST_PLANNING folds into generation)
STAGE_AGENTS = {
    sm.REQUIREMENT_ANALYSIS: RequirementAnalyzerAgent(),
    sm.SERVICE_PLANNING: ServicePlannerAgent(),
    sm.TEST_GENERATION: TestGeneratorAgent(),
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
    sm.TEST_GENERATION: sm.RUNNING,
    sm.TEST_REVIEW: sm.WAITING_FOR_REVIEW,
    sm.CODE_GENERATION: sm.RUNNING,
    sm.API_EXECUTION: sm.EXECUTING,
    sm.CODE_VALIDATION: sm.VALIDATING,
    sm.TRACEABILITY: sm.RUNNING,
    sm.EVIDENCE_GENERATION: sm.GENERATING_EVIDENCE,
    sm.EVIDENCE_REVIEW: sm.WAITING_FOR_APPROVAL,
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

            # Terminal / exception
            if stage == sm.DONE or state.get("status") in sm.EXCEPTION:
                break

            # Human checkpoint: create a pending approval and stop.
            if stage in sm.HUMAN_CHECKPOINTS:
                self._open_checkpoint(workflow_id, stage, state)
                break

            agent = STAGE_AGENTS.get(stage)
            if agent is None:
                # Stage with no dedicated agent (CREATED, TEST_PLANNING, CODE_GENERATION,
                # TRACEABILITY) — advance directly.
                state["current_stage"] = sm.next_stage(stage)
                continue

            state = agent.run(workflow_id, state)
            if state.get("status") in sm.EXCEPTION:
                break

        self._persist(workflow_id, state)
        return state

    def resume(self, workflow_id, state, checkpoint):
        """Called after a human approves a checkpoint."""
        state["current_stage"] = sm.next_stage(checkpoint)
        if state.get("status") in (sm.WAITING_FOR_REVIEW, sm.WAITING_FOR_APPROVAL, sm.BLOCKED):
            state["status"] = sm.RUNNING
        return self.advance(workflow_id, state)

    def _open_checkpoint(self, workflow_id, stage, state):
        import uuid
        stage_to_approval = {
            sm.TEST_REVIEW: "TEST_REVIEW",
            sm.EVIDENCE_REVIEW: "EVIDENCE_REVIEW",
            sm.ALM_APPROVAL: "ALM_APPROVAL",
        }
        create_approval(str(uuid.uuid4()), workflow_id, stage_to_approval.get(stage, stage))
        state["status"] = STAGE_STATUS[stage]
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
