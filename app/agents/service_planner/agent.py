import json
from app.agents.base import BaseAgent
from app.llm.model_router.router import get_router
from app.workflows.state_machine import TEST_PLANNING, BLOCKED

_SYSTEM_PROMPT = """You are a software architect planning API test coverage.

Given the API contracts (service, method, path) and the story context, produce a
service-by-service test plan. Also, if the story defines any API endpoints or payload fields, extract them explicitly. Return a valid JSON object:

{
  "impacted_services": ["service_name_1", "service_name_2"],
  "extracted_apis": [
    {
      "method": "POST",
      "url": "/api/example/resource",
      "purpose": "Brief description of what this API does based on the story",
      "payload_schema": {
        "field_name": "data_type (required/optional, constraints)"
      }
    }
  ],
  "dependency_graph": {
    "nodes": ["service_name_1", "service_name_2"],
    "edges": [{"from": "service_name_1", "to": "service_name_2", "reason": "calls downstream"}]
  },
  "test_plan": [
    {
      "service": "service_name_1",
      "endpoints": [{"method": "POST", "path": "/api/...", "test_priority": "high", "notes": "..."}],
      "test_strategy": "integration"
    }
  ]
}



Rules:
1. Only include services that appear in the provided contracts.
2. Identify dependencies between services based on the endpoint paths and request/response shapes.
3. Assign test_priority: high for mutation endpoints (POST/PUT/DELETE), medium for reads (GET).
"""


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

        story = state.get("story", {})
        analysis = state.get("analysis", {})

        print(f"\n[ServicePlanner] Planning API architecture and test strategy for {len(contracts)} contracts...")
        for c in contracts:
            print(f"   • Endpoint: {c.get('method', 'GET')} {c.get('path', '/')} (Service: {c.get('service', 'Service')})")

        # Build a rich prompt with contracts + story context
        contract_lines = []
        for c in contracts:
            contract_lines.append(f"  - {c.get('method', 'GET')} {c.get('path', '/')} (service: {c.get('service', 'unknown')})")
        contracts_text = "\n".join(contract_lines)

        prompt = f"""Story: {story.get('title', '')} — {story.get('description', '')}

API Contracts:
{contracts_text}

Analysis summary:
- Positive scenarios: {len(analysis.get('positive_scenarios', []))}
- Negative scenarios: {len(analysis.get('negative_scenarios', []))}
- Boundary scenarios: {len(analysis.get('boundary_scenarios', []))}
"""

        router = get_router()
        print(f"[ServicePlanner] Calling LLM ({router._client.__class__.__name__})...")
        result = router.generate_structured(
            "service_planning",
            prompt=prompt,
            system=_SYSTEM_PROMPT)

        print(f"[ServicePlanner] LLM Output Received in {result.latency_ms}ms | Model: {result.model} (is_mock={result.is_mock})")

        # Parse LLM response, fallback to contract extraction
        service_plan = self._parse_plan(result, contracts)
        impacted = service_plan.get("impacted_services", [])
        print(f"[ServicePlanner] Impacted Microservices: {impacted}")
        for item in service_plan.get("test_plan", []):
            svc = item.get("service", "Service")
            strategy = item.get("test_strategy", "unit/integration")
            print(f"   • Service '{svc}' (Strategy: {strategy}):")
            for ep in item.get("endpoints", []):
                print(f"     - {ep.get('method', 'GET')} {ep.get('path', '/')} [Priority: {ep.get('test_priority', 'high')}]")

        state["service_plan"] = service_plan
        if "extracted_apis" in service_plan:
            state["extracted_apis"] = service_plan["extracted_apis"]
        state["current_stage"] = TEST_PLANNING
        self._record(workflow_id, "service_planning", model_name=result.model,
                     latency_ms=result.latency_ms,
                     output_summary={"services": len(impacted)})
        return state

    def _parse_plan(self, result, contracts):
        """Parse Gemini's service plan. Fallback to contract-derived plan."""
        if not result.is_mock:
            try:
                parsed = json.loads(result.text)
                if isinstance(parsed, dict) and "impacted_services" in parsed:
                    parsed["model"] = result.model
                    parsed["is_mock"] = result.is_mock
                    return parsed
            except (json.JSONDecodeError, TypeError):
                print("[ServicePlanner] Could not parse LLM JSON, using contract-derived plan.")

        # Fallback: derive from contracts
        services = list({c.get("service", "unknown") for c in contracts})
        endpoints_by_service = {}
        for c in contracts:
            svc = c.get("service", "unknown")
            endpoints_by_service.setdefault(svc, []).append({
                "method": c.get("method", "GET"),
                "path": c.get("path", "/"),
                "test_priority": "high" if c.get("method", "GET") in ("POST", "PUT", "DELETE") else "medium",
            })

        return {
            "impacted_services": services,
            "dependency_graph": {"nodes": services, "edges": []},
            "test_plan": [
                {"service": svc, "endpoints": eps, "test_strategy": "integration"}
                for svc, eps in endpoints_by_service.items()
            ],
            "model": result.model,
            "is_mock": result.is_mock,
        }

