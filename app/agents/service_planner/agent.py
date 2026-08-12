from app.agents.base import BaseAgent
from app.llm.model_router.router import get_router
from app.workflows.state_machine import TEST_PLANNING, BLOCKED


class ServicePlannerAgent(BaseAgent):
    name = "service_planner"

    def run(self, workflow_id, state):
        contracts = state.get("api_contracts", [])
        if not contracts:
            state.setdefault("errors", []).append(
                {"agent": self.name, "message": "No API contracts — planning exception."})
            state["status"] = BLOCKED
            self._record(workflow_id, "service_planning", status="BLOCKED")
            return state

        router = get_router()
        result = router.generate_structured(
            "service_planning",
            prompt=f"Contracts: {contracts}",
            system="Identify impacted services, dependencies, and a service-by-service test plan.")

        state["service_plan"] = {
            "impacted_services": [c.get("service") for c in contracts],
            "dependency_graph": {"nodes": [c.get("service") for c in contracts], "edges": []},
            "model": result.model, "is_mock": result.is_mock,
        }
        state["current_stage"] = TEST_PLANNING
        self._record(workflow_id, "service_planning", model_name=result.model, latency_ms=result.latency_ms)
        return state
