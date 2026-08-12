from app.agents.base import BaseAgent
from app.llm.model_router.router import get_router
from app.guardrails.engine import check_input
from app.workflows.state_machine import SERVICE_PLANNING, BLOCKED


class RequirementAnalyzerAgent(BaseAgent):
    name = "requirement_analyzer"

    def run(self, workflow_id, state):
        story = state.get("story", {})
        acs = state.get("acceptance_criteria", [])
        text = f"{story.get('title','')} {story.get('description','')}"

        clean, detail = check_input(text, workflow_id)
        if not clean:
            state["status"] = BLOCKED
            state.setdefault("errors", []).append({"agent": self.name, "message": detail})
            return state

        if not acs:
            # Never invent missing rules — flag clarification.
            state["clarification_required"] = True
            state.setdefault("errors", []).append(
                {"agent": self.name, "message": "No acceptance criteria — clarification required."})
            state["status"] = BLOCKED
            self._record(workflow_id, "requirement_analysis", status="BLOCKED")
            return state

        router = get_router()
        result = router.generate_structured(
            "requirement_analysis",
            prompt=f"Story: {text}\nAcceptance Criteria: {acs}",
            system="Decompose into scenarios; flag ambiguities; never invent rules.")

        analysis = {
            "business_rules": [],
            "positive_scenarios": [{"id": self.nid("SCN"), "desc": "valid input authorizes"}],
            "negative_scenarios": [{"id": self.nid("SCN"), "desc": "expired card rejected"}],
            "boundary_scenarios": [{"id": self.nid("SCN"), "desc": "amount at limit"}],
            "validation_scenarios": [],
            "error_scenarios": [],
            "ambiguities": [],
            "traceability_ids": [self.nid("REQ")],
            "model": result.model,
            "is_mock": result.is_mock,
        }
        state["analysis"] = analysis
        state["current_stage"] = SERVICE_PLANNING
        self._record(workflow_id, "requirement_analysis", model_name=result.model,
                     latency_ms=result.latency_ms, output_summary={"scenarios": 3})
        return state
