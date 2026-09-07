import json
import re
from app.agents.base import BaseAgent
from app.llm.model_router.router import get_router
from app.workflows.state_machine import TEST_PLANNING, BLOCKED

_SYSTEM_PROMPT = """You are a principal software architect and API test engineer planning manual and automated test execution.

CRITICAL DIRECTIVES:
1. STRICT GROUNDING IN CODEBASE: You MUST inspect the provided "Discovered Real Implemented Routes in Codebase" and "Git Codebase Context". You MUST select the EXACT API endpoint (method + path, e.g. `/api/auth/change-password`, `/api/users/register`, `/api/orders/{id}`) from the codebase that matches the User Story.
2. ZERO PLACEHOLDERS: NEVER invent generic placeholder paths (e.g. `/api/resource`, `/api/endpoint`, `/api/resource/action` are STRICTLY FORBIDDEN). If real routes are provided, you MUST choose the matching real route.
3. EXACT REQUEST PAYLOAD SCHEMA: Inspect the function signature, `@router` / `@PostMapping` parameter, and the corresponding Pydantic `BaseModel` / DTO / Schema in the Codebase Context. Return the actual field names with their exact types and constraints.
4. EXACT EXPECTED RESPONSE SCHEMA: Inspect the controller method's `response_model` or return DTO class. Return the exact structure and field names.
5. CONCRETE, REALISTIC TEST SCENARIOS: For every scenario (`actual_payload` and `actual_response`), provide authentic, realistic sample data matching the exact fields for this specific story entity.

Return a valid JSON object matching this structure:
{
  "impacted_services": ["ServiceName"],
  "extracted_apis": [
    {
      "method": "POST",
      "url": "http://server-base-url/api/exact/codebase/route",
      "path": "/api/exact/codebase/route",
      "purpose": "Accurate description of what this endpoint does",
      "source_file": "controllers/auth_controller.py",
      "handler_function": "handle_action()",
      "payload_schema": {
        "field_name": "string (required, description of field)"
      },
      "response_schema": {
        "status_code": 200,
        "description": "Successful operation response",
        "body": {
          "status": "string",
          "data": "object"
        }
      },
      "test_scenarios": [
        {
          "id": "TS-01",
          "title": "200 OK — Successful Valid Request",
          "status_code": 200,
          "status_text": "200 OK",
          "scenario_type": "POSITIVE",
          "description": "Executing request with valid payload returns 200 OK",
          "actual_payload": {
            "field_name": "sample_valid_value"
          },
          "actual_response": {
            "status": "success",
            "message": "Operation completed successfully"
          }
        },
        {
          "id": "TS-02",
          "title": "400 Bad Request / 404 Not Found — Invalid Request",
          "status_code": 400,
          "status_text": "400 Bad Request",
          "scenario_type": "NEGATIVE",
          "description": "Submitting invalid identifier returns error",
          "actual_payload": {
            "field_name": "invalid_value"
          },
          "actual_response": {
            "detail": "Validation error"
          }
        }
      ]
    }
  ],
  "dependency_graph": {
    "nodes": ["ServiceName"],
    "edges": []
  },
  "test_plan": [
    {
      "service": "ServiceName",
      "endpoints": [
        {"method": "POST", "path": "/api/exact/codebase/route", "test_priority": "high", "notes": "Verify core functionality"}
      ],
      "test_strategy": "integration"
    }
  ]
}
"""


class ServicePlannerAgent(BaseAgent):
    name = "service_planner"

    def run(self, workflow_id, state):
        contracts = state.get("api_contracts", [])
        project = state.get("project", {})
        story = state.get("story", {})
        analysis = state.get("analysis", {})

        # Extract codebase context and detect base URL from Git workspace or project configuration
        codebase_context = ""
        discovered_routes = []
        base_url = state.get("environment") or project.get("base_url") or project.get("api_base_url") or project.get("environment_url") or ""
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
                codebase_context = ws.extract_api_route_context(max_files=35, max_bytes_per_file=8000)
                discovered_routes = ws.parse_codebase_routes()
                if not base_url:
                    base_url = ws.detect_base_url()
                if codebase_context:
                    print(f"[ServicePlanner] Injected {len(codebase_context)} chars of API & Route code from Git workspace (Base URL: {base_url}).")
                if discovered_routes:
                    print(f"[ServicePlanner] Discovered {len(discovered_routes)} implemented routes in repository:")
                    for r in discovered_routes[:10]:
                        print(f"   * {r['method']} {r['path']} ({r['source_file']})")
            except Exception as e:
                print(f"[ServicePlanner] Note: Could not read Git workspace: {e}")

        if not base_url:
            base_url = "http://localhost:8080"

        print(f"\n[ServicePlanner] Planning API architecture and test strategy for story '{story.get('title', '')}'...")
        for c in contracts:
            print(f"   • Endpoint: {c.get('method', 'GET')} {c.get('path', '/')} (Service: {c.get('service', 'Service')})")

        # Build prompt with contracts, story context, acceptance criteria, and codebase snippets
        contract_lines = []
        for c in contracts:
            contract_lines.append(f"  - {c.get('method', 'GET')} {c.get('path', '/')} (service: {c.get('service', 'unknown')})")
        contracts_text = "\n".join(contract_lines) if contract_lines else "None provided in DB - inspect codebase."

        acs = state.get("acceptance_criteria", [])
        acs_lines = []
        for i, ac in enumerate(acs, start=1):
            ac_txt = ac.get("text") if isinstance(ac, dict) else str(ac)
            ac_k = ac.get("ac_key") if isinstance(ac, dict) else f"AC-{i:02d}"
            acs_lines.append(f"  - {ac_k}: {ac_txt}")
        acs_text = "\n".join(acs_lines) if acs_lines else "None"

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
        if discovered_routes:
            routes_summary = "\n".join(f"  - {r['method']} {r['path']} (Source: {r['source_file']})" for r in discovered_routes)
            prompt += f"\n\n### Discovered Real Implemented Routes in Codebase (STRICTLY USE IF MATCHING STORY):\n{routes_summary}\n"

        if codebase_context:
            prompt += f"\n\n### Git Codebase Context (Controllers, Routes, DTOs & Models):\n{codebase_context}\n"

        router = get_router()
        print(f"[ServicePlanner] Calling LLM ({router._client.__class__.__name__})...")
        result = router.generate_structured(
            "service_planning",
            prompt=prompt,
            system=_SYSTEM_PROMPT)

        print(f"[ServicePlanner] LLM Output Received in {result.latency_ms}ms | Model: {result.model} (is_mock={result.is_mock})")

        # Parse LLM response, fallback to discovered routes or contract extraction
        service_plan = self._parse_plan(result, contracts, story, base_url, acs, discovered_routes=discovered_routes)
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

                # Ensure test_scenarios exists
                if "test_scenarios" not in ep or not ep["test_scenarios"]:
                    ep["test_scenarios"] = self._synthesize_test_scenarios(ep, acs)

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
                    "test_scenarios": ep.get("test_scenarios", []),
                })
            if enriched_contracts:
                state["api_contracts"] = enriched_contracts

        state["current_stage"] = TEST_PLANNING
        self._record(workflow_id, "service_planning", model_name=result.model,
                     latency_ms=result.latency_ms,
                     output_summary={"services": len(impacted), "extracted_apis": len(extracted_apis)})
        return state

    def _synthesize_test_scenarios(self, ep, acs):
        """Synthesize realistic manual test scenarios with actual concrete payloads and responses."""
        method = ep.get("method", "POST").upper()
        path = ep.get("path", "/api/resource")
        schema = ep.get("payload_schema") or {}

        # Generate realistic sample payload from schema keys
        sample_positive_payload = {}
        if schema and isinstance(schema, dict):
            for k in schema.keys():
                k_low = k.lower()
                if "email" in k_low:
                    sample_positive_payload[k] = "test.user@example.com"
                elif "prospect_id" in k_low or "prospect" in k_low:
                    sample_positive_payload[k] = "PR-10029"
                elif "policy_id" in k_low:
                    sample_positive_payload[k] = "POL-8821"
                elif "analysis_type" in k_low or "type" in k_low:
                    sample_positive_payload[k] = "full"
                elif "name" in k_low or "title" in k_low:
                    sample_positive_payload[k] = "Standard Campaign / Prospect Analysis"
                elif "phone" in k_low or "mobile" in k_low:
                    sample_positive_payload[k] = "+8801712345678"
                elif "csv" in k_low or "content" in k_low:
                    sample_positive_payload[k] = "name,email,age\nAlice,alice@example.com,32"
                elif "source" in k_low:
                    sample_positive_payload[k] = "upload.csv"
                elif "pass" in k_low:
                    sample_positive_payload[k] = "SecurePass@123"
                elif "age" in k_low or "count" in k_low or "number" in k_low:
                    sample_positive_payload[k] = 30
                elif "score" in k_low:
                    sample_positive_payload[k] = 85.5
                elif "channel" in k_low:
                    sample_positive_payload[k] = "email"
                else:
                    sample_positive_payload[k] = f"valid_{k}"

        if not sample_positive_payload and method in ("POST", "PUT", "PATCH"):
            import re
            slug = path.strip("/").split("/")[-1] or "resource"
            slug = re.sub(r"[{}]", "", slug).rstrip("s") or "item"
            sample_positive_payload = {f"{slug}_id": f"{slug.upper()}-1001", "name": f"Valid {slug.title()}", "status": "ACTIVE"}

        scenarios = [
            {
                "id": "TS-01",
                "title": f"{200 if method != 'POST' else 200} Success (Valid Request)",
                "status_code": 200,
                "status_text": "200 OK",
                "scenario_type": "POSITIVE",
                "description": f"Executing {method} {path} with valid inputs processes successfully",
                "actual_payload": sample_positive_payload if method in ("POST", "PUT", "PATCH") else None,
                "actual_response": {
                    "status": "success",
                    "data": sample_positive_payload,
                    "timestamp": "2026-09-04T12:00:00Z"
                }
            }
        ]

        # 2. Negative scenario: Invalid or non-existent identifier
        invalid_id_payload = dict(sample_positive_payload)
        id_key = next((k for k in invalid_id_payload.keys() if "id" in k.lower()), None)
        if id_key:
            invalid_id_payload[id_key] = "NON_EXISTENT_ID_999"
            scenarios.append({
                "id": "TS-02",
                "title": "404 Not Found (Invalid Identifier)",
                "status_code": 404,
                "status_text": "404 Not Found",
                "scenario_type": "NEGATIVE",
                "description": f"Submitting a non-existent {id_key} returns a 404 error response",
                "actual_payload": invalid_id_payload,
                "actual_response": {
                    "detail": f"{id_key} not found"
                }
            })

        # 3. Validation failure scenario (400 / 422)
        scenarios.append({
            "id": f"TS-0{len(scenarios)+1}",
            "title": "422 Unprocessable Entity (Missing Mandatory Fields)",
            "status_code": 422,
            "status_text": "422 Unprocessable Entity",
            "scenario_type": "NEGATIVE",
            "description": f"Omission of required parameters in {method} {path} is rejected by schema validator",
            "actual_payload": {},
            "actual_response": {
                "detail": [{"loc": ["body"], "msg": "field required", "type": "value_error.missing"}]
            }
        })

        return scenarios

    def _parse_plan(self, result, contracts, story=None, base_url="http://localhost:8080", acs=None, discovered_routes=None):
        """Parse Gemini's service plan with strict grounding against real codebase routes."""
        discovered_routes = discovered_routes or []
        parsed = None

        if not result.is_mock:
            try:
                parsed = json.loads(result.text)
            except (json.JSONDecodeError, TypeError):
                print("[ServicePlanner] Could not parse LLM JSON, using codebase route grounding.")
                parsed = None

        if isinstance(parsed, dict) and ("impacted_services" in parsed or "extracted_apis" in parsed):
            extracted = parsed.get("extracted_apis") or []
            
            # Verify extracted routes are not generic placeholders if real routes exist
            if discovered_routes and extracted:
                valid_extracted = []
                story_words = set(re.findall(r"\w+", f"{(story or {}).get('title', '')} {(story or {}).get('description', '')}".lower()))
                
                for ep in extracted:
                    ep_path = (ep.get("path") or ep.get("url") or "").lower()
                    # If endpoint is placeholder, find best matching discovered route
                    if any(ph in ep_path for ph in ("/api/resource", "/api/endpoint", "example.com", "server-base-url")) or not ep_path:
                        # Score discovered routes based on story word overlap
                        best_route = None
                        best_score = -1
                        for r in discovered_routes:
                            r_words = set(re.findall(r"\w+", r["path"].lower()))
                            score = len(story_words.intersection(r_words))
                            if r["method"].upper() == ep.get("method", "GET").upper():
                                score += 2
                            if score > best_score:
                                best_score = score
                                best_route = r
                        if best_route:
                            ep["path"] = best_route["path"]
                            ep["method"] = best_route["method"]
                            ep["url"] = f"{base_url.rstrip('/')}/{best_route['path'].lstrip('/')}"
                            ep["source_file"] = best_route.get("source_file", ep.get("source_file"))
                    valid_extracted.append(ep)
                parsed["extracted_apis"] = valid_extracted

            parsed["model"] = result.model
            parsed["is_mock"] = result.is_mock
            if not parsed.get("impacted_services"):
                parsed["impacted_services"] = ["CoreService"]
            return parsed

        # Fallback: ground strictly in discovered routes from codebase or explicit contracts
        story_text = f"{(story or {}).get('title', '')} {(story or {}).get('description', '')}".lower()
        story_words = set(re.findall(r"\w+", story_text))
        matched_routes = []

        if discovered_routes:
            for r in discovered_routes:
                r_words = set(re.findall(r"\w+", r["path"].lower()))
                overlap = len(story_words.intersection(r_words))
                if overlap > 0:
                    matched_routes.append((overlap, r))
            matched_routes.sort(key=lambda x: x[0], reverse=True)

        selected_routes = [r[1] for r in matched_routes[:4]] if matched_routes else discovered_routes[:3]

        if not selected_routes and contracts:
            selected_routes = contracts

        if not selected_routes:
            clean_name = "".join(c for c in (story or {}).get("title", "resource") if c.isalnum() or c in " -_").strip()
            endpoint_slug = clean_name.lower().replace(" ", "-") or "api"
            selected_routes = [{"method": "POST" if "create" in story_text else "GET", "path": f"/{endpoint_slug}"}]

        services = ["CoreService"]
        endpoints_by_service = {}
        extracted_apis = []

        for r in selected_routes:
            svc = r.get("service", "CoreService")
            method = r.get("method", "GET").upper()
            rel_path = r.get("path", "/api")
            full_url = f"{base_url.rstrip('/')}/{rel_path.lstrip('/')}"
            endpoints_by_service.setdefault(svc, []).append({
                "method": method,
                "path": rel_path,
                "test_priority": "high" if method in ("POST", "PUT", "DELETE", "PATCH") else "medium",
            })
            slug = rel_path.strip("/").split("/")[-1] or "item"
            slug = re.sub(r"[{}]", "", slug).rstrip("s") or "item"
            ep_obj = {
                "method": method,
                "url": full_url,
                "path": rel_path,
                "purpose": f"Perform {method} operation on {rel_path}",
                "payload_schema": r.get("request_schema") or ({
                    f"{slug}_id": f"string (required, {slug} identifier)",
                    "name": "string (required)",
                    "status": "string (optional: ACTIVE, PENDING)"
                } if method in ("POST", "PUT", "PATCH") else None),
                "response_schema": r.get("response_schema") or {
                    "status_code": 200,
                    "body": {
                        "status": "success",
                        "data": "object"
                    }
                }
            }
            ep_obj["test_scenarios"] = self._synthesize_test_scenarios(ep_obj, acs or [])
            extracted_apis.append(ep_obj)

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

