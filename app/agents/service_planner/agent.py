import json
from app.agents.base import BaseAgent
from app.llm.model_router.router import get_router
from app.workflows.state_machine import TEST_PLANNING, BLOCKED

_SYSTEM_PROMPT = """You are a senior software architect and API designer planning test coverage and analyzing codebase API contracts.

Analyze the provided User Story, Acceptance Criteria, Server Base URL, and Git Codebase Context (Controllers, Routes, DTOs, Schemas) to accurately extract ONLY the target API endpoints, Request Payload schemas, and Expected Response schemas required for this specific story.

Return a valid JSON object matching this structure:
{
  "impacted_services": ["service_name_1"],
  "extracted_apis": [
    {
      "method": "POST",
      "url": "http://localhost:8080/api/users",
      "path": "/api/users",
      "purpose": "Create a new customer record with server-side validation",
      "source_file": "src/controllers/UserController.py",
      "handler_function": "UserController.create_customer",
      "payload_schema": {
        "address": "string (optional)",
        "email": "string (required, valid email format)",
        "first_name": "string (required, 2-50 chars)",
        "last_name": "string (required, 2-50 chars)",
        "phone": "string (required, regex ^\\+?\\d{7,15}$)"
      },
      "response_schema": {
        "status_code": 201,
        "description": "Customer entity created and returned",
        "body": {
          "id": "number (auto-increment primary key)",
          "email": "string",
          "first_name": "string",
          "last_name": "string",
          "phone": "string",
          "address": "string",
          "created_at": "string (ISO-8601 timestamp)"
        }
      }
    }
  ],
  "dependency_graph": {
    "nodes": ["service_name_1"],
    "edges": []
  },
  "test_plan": [
    {
      "service": "service_name_1",
      "endpoints": [
        {"method": "POST", "path": "/api/users", "test_priority": "high", "notes": "Validate customer creation & payload"}
      ],
      "test_strategy": "integration"
    }
  ]
}

STRICT INSTRUCTIONS:
1. ONLY STORY-RELEVANT APIS: Extract ONLY the API endpoints that are strictly needed to implement this specific User Story (e.g. if the story is 'Create Customer', extract ONLY the creation endpoint). DO NOT list unrelated GET, PUT, or DELETE endpoints unless the Acceptance Criteria explicitly ask to verify or query them.
2. FULL URL: The 'url' field MUST be the complete URL with protocol, host, and port using the provided Server Base URL (e.g., 'http://localhost:8080/api/users' or 'http://localhost:5000/api/customers'). Provide the relative endpoint in 'path'.
3. REAL CODEBASE RESPONSE SCHEMA: Inspect the controller method's return type, return statements, and the corresponding response DTO / Entity / Model class in the Git Codebase Context. Return EVERY field defined in that response class/model. DO NOT invent generic mock responses (like '{"id": "number", "status": "success"}') if the code returns an actual entity/DTO structure.
4. REAL CODEBASE REQUEST PAYLOAD: Inspect the controller's request body parameter and the corresponding DTO / Model / Schema class in the Git Codebase Context. Return all fields with their exact types and validation constraints/annotations (@NotNull, @Email, regex, etc.).
5. EXACT STATUS CODE: Use the exact HTTP status code returned by the controller for success (e.g. 201 Created for POST, 200 OK for GET/PUT, 204 No Content for DELETE).
"""


class ServicePlannerAgent(BaseAgent):
    name = "service_planner"

    def run(self, workflow_id, state):
        contracts = state.get("api_contracts", [])
        project = state.get("project", {})
        story = state.get("story", {})
        analysis = state.get("analysis", {})

        # Extract codebase context and detect base URL from Git workspace
        codebase_context = ""
        base_url = "http://localhost:8080"
        project_uuid = project.get("uuid") or project.get("id")
        git_repo_url = project.get("git_repo_url", "")
        if project_uuid and git_repo_url:
            try:
                from app.tools.repository.workspace import GitWorkspace
                ws = GitWorkspace(
                    project_uuid=str(project_uuid),
                    repo_url=git_repo_url,
                    branch=project.get("git_branch", "main")
                )
                codebase_context = ws.extract_api_route_context(max_files=25, max_bytes_per_file=6000)
                base_url = ws.detect_base_url()
                if codebase_context:
                    print(f"[ServicePlanner] Injected {len(codebase_context)} chars of API & Route code from Git workspace (Base URL: {base_url}).")
            except Exception as e:
                print(f"[ServicePlanner] Note: Could not read Git workspace: {e}")

        if not contracts and not codebase_context:
            state.setdefault("errors", []).append(
                {"agent": self.name, "message": "No API contracts or codebase found — planning exception."})
            state["status"] = BLOCKED
            self._record(workflow_id, "service_planning", status="BLOCKED")
            return state

        print(f"\n[ServicePlanner] Planning API architecture and test strategy for story '{story.get('title', '')}'...")
        for c in contracts:
            print(f"   • Endpoint: {c.get('method', 'GET')} {c.get('path', '/')} (Service: {c.get('service', 'Service')})")

        # Build prompt with contracts, story context, acceptance criteria, and codebase snippets
        contract_lines = []
        for c in contracts:
            contract_lines.append(f"  - {c.get('method', 'GET')} {c.get('path', '/')} (service: {c.get('service', 'unknown')})")
        contracts_text = "\n".join(contract_lines) if contract_lines else "None provided in DB - analyze codebase."

        acs = state.get("acceptance_criteria", [])
        acs_text = "\n".join(f"  - AC-{i+1}: {ac}" for i, ac in enumerate(acs)) if acs else "None"

        prompt = f"""User Story: {story.get('title', '')}
Description:
{story.get('description', 'No description provided.')}

Acceptance Criteria:
{acs_text}

Server Base URL: {base_url}

Known API Contracts:
{contracts_text}

Analysis summary:
- Positive scenarios: {len(analysis.get('positive_scenarios', []))}
- Negative scenarios: {len(analysis.get('negative_scenarios', []))}
- Boundary scenarios: {len(analysis.get('boundary_scenarios', []))}
"""
        if codebase_context:
            prompt += f"\n\n### Git Codebase Context (Controllers, Routes, DTOs & Models):\n{codebase_context}\n"

        router = get_router()
        print(f"[ServicePlanner] Calling LLM ({router._client.__class__.__name__})...")
        result = router.generate_structured(
            "service_planning",
            prompt=prompt,
            system=_SYSTEM_PROMPT)

        print(f"[ServicePlanner] LLM Output Received in {result.latency_ms}ms | Model: {result.model} (is_mock={result.is_mock})")

        # Parse LLM response, fallback to contract extraction
        service_plan = self._parse_plan(result, contracts, story, base_url)
        impacted = service_plan.get("impacted_services", [])
        print(f"[ServicePlanner] Impacted Microservices: {impacted}")
        for item in service_plan.get("test_plan", []):
            svc = item.get("service", "Service")
            strategy = item.get("test_strategy", "unit/integration")
            print(f"   • Service '{svc}' (Strategy: {strategy}):")
            for ep in item.get("endpoints", []):
                print(f"     - {ep.get('method', 'GET')} {ep.get('path', '/')} [Priority: {ep.get('test_priority', 'high')}]")

        state["service_plan"] = service_plan
        extracted_apis = service_plan.get("extracted_apis", [])
        if extracted_apis:
            # Guarantee full URL format on each extracted api
            for ep in extracted_apis:
                url_val = ep.get("url", "")
                if url_val.startswith("/"):
                    ep["path"] = url_val
                    ep["url"] = f"{base_url.rstrip('/')}{url_val}"
                elif not url_val.startswith("http://") and not url_val.startswith("https://"):
                    ep["path"] = f"/{url_val.lstrip('/')}"
                    ep["url"] = f"{base_url.rstrip('/')}/{url_val.lstrip('/')}"
                elif "path" not in ep:
                    import urllib.parse
                    parsed = urllib.parse.urlparse(url_val)
                    ep["path"] = parsed.path or "/"

            state["extracted_apis"] = extracted_apis
            # Sync or enrich api_contracts for downstream test generators
            enriched_contracts = []
            for ep in extracted_apis:
                enriched_contracts.append({
                    "service": impacted[0] if impacted else "CoreService",
                    "method": ep.get("method", "GET").upper(),
                    "path": ep.get("path", ep.get("url", "/api")),
                    "url": ep.get("url"),
                    "purpose": ep.get("purpose", ""),
                    "request_schema": ep.get("payload_schema"),
                    "response_schema": ep.get("response_schema"),
                })
            if enriched_contracts:
                state["api_contracts"] = enriched_contracts

        state["current_stage"] = TEST_PLANNING
        self._record(workflow_id, "service_planning", model_name=result.model,
                     latency_ms=result.latency_ms,
                     output_summary={"services": len(impacted), "extracted_apis": len(extracted_apis)})
        return state

    def _parse_plan(self, result, contracts, story=None, base_url="http://localhost:8080"):
        """Parse Gemini's service plan. Fallback to contract-derived plan."""
        if not result.is_mock:
            try:
                parsed = json.loads(result.text)
                if isinstance(parsed, dict) and ("impacted_services" in parsed or "extracted_apis" in parsed):
                    parsed["model"] = result.model
                    parsed["is_mock"] = result.is_mock
                    if not parsed.get("impacted_services"):
                        parsed["impacted_services"] = ["CoreService"]
                    return parsed
            except (json.JSONDecodeError, TypeError):
                print("[ServicePlanner] Could not parse LLM JSON, using fallback plan.")

        # Fallback: derive from contracts or story
        services = list({c.get("service", "unknown") for c in contracts}) or ["CoreService"]
        endpoints_by_service = {}
        extracted_apis = []

        for c in contracts:
            svc = c.get("service", "CoreService")
            method = c.get("method", "GET").upper()
            rel_path = c.get("path", "/api")
            full_url = f"{base_url.rstrip('/')}/{rel_path.lstrip('/')}"
            endpoints_by_service.setdefault(svc, []).append({
                "method": method,
                "path": rel_path,
                "test_priority": "high" if method in ("POST", "PUT", "DELETE", "PATCH") else "medium",
            })
            extracted_apis.append({
                "method": method,
                "url": full_url,
                "path": rel_path,
                "purpose": f"Perform {method} operation on {rel_path}",
                "payload_schema": c.get("request_schema") or ({"data": "object"} if method in ("POST", "PUT", "PATCH") else None),
                "response_schema": c.get("response_schema") or {
                    "status_code": 201 if method == "POST" else 200,
                    "body": {"success": True}
                }
            })

        return {
            "impacted_services": services,
            "extracted_apis": extracted_apis,
            "dependency_graph": {"nodes": services, "edges": []},
            "test_plan": [
                {"service": svc, "endpoints": eps, "test_strategy": "integration"}
                for svc, eps in endpoints_by_service.items()
            ],
            "model": result.model,
            "is_mock": result.is_mock,
        }

