import uuid
import json
from app.agents.base import BaseAgent
from app.llm.model_router.router import get_router
from app.repositories.test_repo import insert_test_case
from app.workflows.state_machine import TEST_REVIEW

_SYSTEM_PROMPT = """You are an expert QA and Software Architect specializing in Test-Driven Development (TDD).

Given a user story, acceptance criteria, API contracts, and decomposed scenarios:
1. MANDATORY 100% COVERAGE RULE: You MUST generate a dedicated, detailed test case for EVERY SINGLE decomposed scenario provided in the input (including ALL positive, negative, boundary, validation, and error scenarios). Do NOT omit, summarize, truncate, or combine scenarios. If there are 10 decomposed scenarios, you MUST output at least 10 test cases (`TC-001` through `TC-010`).
2. AC MAPPING: For each test case, reference the ACTUAL Acceptance Criteria (e.g., 'AC-05: User can be created via POST /api/users with valid fields').
3. REQUEST SPECIFICATION: Provide the specific HTTP method, endpoint, headers, and full JSON body matching the scenario under test.
4. EXPECTED RESPONSE & ASSERTIONS: Provide expected status code, response JSON body, and comprehensive list of assertions.
5. STATUS SOURCE VERIFICATION: If the status code (e.g. 200/201/400/401/403/404/422) is NOT explicitly defined in the provided API contracts or Project KB, set status_source = 'AI_ASSUMPTION' and status_note = 'Not specified in API contract (AI assumption — review required)'. Otherwise set status_source = 'CONTRACT_SPECIFIED'.
6. CODE UNDER TEST: For responsible functions, provide the FULL architectural call chain across layers (e.g., UserController.createUser() -> UserService.createUser() -> UserRepository.save()).

You MUST return a valid JSON object matching this schema:
{
  "test_cases": [
    {
      "test_key": "TC-001",
      "scenario_type": "positive",
      "title": "Successfully create a new user with valid fields",
      "description": "Verify user can be created via POST /api/users with name and email",
      "story_reference": "AC-01: User can be created via POST /api/users with valid name and email",
      "request_spec": {
        "method": "POST",
        "endpoint": "/api/users",
        "headers": {
          "Content-Type": "application/json"
        },
        "body": {
          "name": "John Doe",
          "email": "john.doe@example.com",
          "role": "USER"
        }
      },
      "expected_response_spec": {
        "status_code": 201,
        "status_source": "CONTRACT_SPECIFIED",
        "status_note": "Status 201 defined in OpenAPI contract",
        "response_body": {
          "id": 1,
          "name": "John Doe",
          "email": "john.doe@example.com",
          "role": "USER",
          "createdAt": "2026-08-24T12:00:00Z"
        },
        "assertions": [
          "response.status == 201",
          "response.body.id != null",
          "response.body.email == 'john.doe@example.com'"
        ]
      },
      "expected_result": "API responds with 201 Created and persisted user JSON payload",
      "priority": "high",
      "risk": "medium",
      "responsible_functions": [
        "UserController.createUser()",
        "UserService.createUser()",
        "UserRepository.save()"
      ]
    }
  ]
}

Rules:
- Generate a test case for every positive, negative, boundary, validation, and error scenario.
- Never leave request_spec or expected_response_spec empty.
- If status code is an assumption not in contract, flag it with 'AI_ASSUMPTION'.
- Provide full 3-tier responsible call chain (Controller -> Service -> Repository).
- Do NOT generate full code files in this step; code will be generated post-approval in Stage 7.
"""


class TestGeneratorAgent(BaseAgent):
    name = "test_generator"

    def run(self, workflow_id, state):
        analysis = state.get("analysis", {})
        story = state.get("story", {})
        story_id = story.get("id")
        project = state.get("project", {})
        lang = project.get("target_language", "java")
        framework = project.get("target_framework", "junit5")
        contracts = state.get("api_contracts", [])
        acs = state.get("acceptance_criteria", [])

        # Get RAG context and Workspace summary if available
        rag_context = self._get_rag_context(state, story.get("title", ""))
        workspace_context = self._get_workspace_summary(state)

        contract_summary = self._format_contracts(contracts)
        acs_text = "\n".join(f"  - AC-{i+1:02d}: {ac}" for i, ac in enumerate(acs)) if acs else story.get("description", "")

        scenario_map = [("positive", analysis.get("positive_scenarios", [])),
                        ("negative", analysis.get("negative_scenarios", [])),
                        ("boundary", analysis.get("boundary_scenarios", [])),
                        ("validation", analysis.get("validation_scenarios", [])),
                        ("error", analysis.get("error_scenarios", []))]

        scenario_items = []
        for stype, slist in scenario_map:
            for s in (slist or []):
                s_id = s.get("id", "SCN") if isinstance(s, dict) else "SCN"
                s_desc = s.get("desc", str(s)) if isinstance(s, dict) else str(s)
                scenario_items.append(f"  - [{stype.upper()}] ({s_id}): {s_desc}")
        scenario_list_text = "\n".join(scenario_items) if scenario_items else "No explicit decomposed scenarios provided."
        scenario_count = len(scenario_items)

        # Prompt Gemini to decompose test cases, map story portions, and identify responsible functions
        prompt = f"""User Story: {story.get('title', '')}
Story Description:
{story.get('description', '')}

Acceptance Criteria / Requirements:
{acs_text}

Target Tech: {lang} / {framework}
API Contracts:
{contract_summary}

Total Decomposed Scenarios to generate test cases for ({scenario_count} scenarios):
{scenario_list_text}

Full Decomposed Analysis JSON:
{json.dumps(analysis, default=str, indent=2)}

CRITICAL INSTRUCTION:
You MUST generate a separate, distinct test case (`TC-001`, `TC-002`, ..., `TC-{max(scenario_count, 1):03d}`) for EVERY SINGLE one of the {scenario_count} scenarios listed above. Cover every positive, negative, boundary, validation, and error scenario. Do NOT truncate or omit any scenario.
"""
        if workspace_context:
            prompt += f"\nCodebase Structure & Source Files:\n{workspace_context}\n"
        if rag_context:
            prompt += f"\nKnowledge Base Context:\n{rag_context}\n"

        router = get_router()
        result = router.generate_structured(
            "test_generation",
            prompt=prompt,
            system=_SYSTEM_PROMPT
        )

        parsed_tcs = self._parse_test_cases(result, scenario_map, contracts, story, acs, lang, framework)

        generated = []
        for idx, tc_data in enumerate(parsed_tcs, start=1):
            key = tc_data.get("test_key") or f"TC-{idx:03d}"
            tc = {
                "test_key": key,
                "scenario_type": tc_data.get("scenario_type", "positive"),
                "title": tc_data.get("title", f"Test {key}"),
                "description": tc_data.get("description", tc_data.get("title", "")),
                "story_reference": tc_data.get("story_reference") or f"AC-{idx:02d}: {story.get('title', 'Feature Verification')}",
                "request_spec": tc_data.get("request_spec"),
                "expected_response_spec": tc_data.get("expected_response_spec"),
                "expected_result": tc_data.get("expected_result", "Expected behavior satisfies acceptance criteria"),
                "priority": tc_data.get("priority", "high"),
                "risk": tc_data.get("risk", "medium"),
                "origin": "AI_GENERATED",
                "status": "AWAITING_REVIEW",
                "responsible_functions": tc_data.get("responsible_functions", []),
                "generated_code": None,
                "target_language": lang,
                "framework": framework,
            }
            if story_id:
                insert_test_case(str(uuid.uuid4()), workflow_id, story_id, tc)
            generated.append(tc)

        state["generated_tests"] = generated
        state["current_stage"] = TEST_REVIEW  # human checkpoint
        self._record(workflow_id, "test_generation", model_name=result.model,
                     latency_ms=result.latency_ms, output_summary={"count": len(generated), "is_mock": result.is_mock})
        return state

    def _parse_test_cases(self, result, scenario_map, contracts, story, acs, lang, framework):
        """Parse structured test cases, story references, request specs, and responsible functions."""
        raw_tcs = []
        if not result.is_mock:
            try:
                data = json.loads(result.text)
                if isinstance(data, dict) and "test_cases" in data and isinstance(data["test_cases"], list):
                    raw_tcs = data["test_cases"]
                elif isinstance(data, list):
                    raw_tcs = data
            except Exception as e:
                print(f"[TestGenerator] Could not parse structured JSON: {e}")

        service_name = (contracts[0].get("service") if contracts else "User") or "User"
        base_entity = "".join(c for c in service_name if c.isalnum()) or "User"
        if "user" in f"{story.get('title', '')} {story.get('description', '')}".lower():
            base_entity = "User"

        contract_has_status = any(c.get("status_code") or c.get("response_code") for c in contracts)

        # Build normalized list
        normalized = []
        if raw_tcs:
            for idx, tc in enumerate(raw_tcs, start=1):
                method = (tc.get("request_spec") or {}).get("method") or ("POST" if "create" in tc.get("title", "").lower() else "GET")
                endpoint = (tc.get("request_spec") or {}).get("endpoint") or f"/api/{base_entity.lower()}s"
                if endpoint == "/api/resource" or endpoint.startswith("/api/resource"):
                    endpoint = f"/api/{base_entity.lower()}s"

                # Ensure clean AC mapping
                story_ref = tc.get("story_reference", "")
                if not story_ref or story_ref.lower().startswith("as a") or "user story" in story_ref.lower():
                    if acs and idx <= len(acs):
                        story_ref = f"AC-{idx:02d}: {acs[idx-1]}"
                    else:
                        story_ref = f"AC-{idx:02d}: {base_entity} {tc.get('title', 'operation')} verification"

                # Ensure request spec body dynamically if LLM omitted it
                req_spec = tc.get("request_spec") or {}
                req_body = req_spec.get("body")
                if method == "POST" and not req_body:
                    if base_entity.lower() == "user":
                        req_body = {
                            "name": "Rohan",
                            "email": "rohan@gmail.com",
                            "password": "Password@123"
                        }
                    else:
                        req_body = {
                            f"{base_entity.lower()}Name": f"Sample {base_entity}",
                            "status": "ACTIVE",
                            "description": f"Test {base_entity} for {tc.get('test_key', 'TC')}"
                        }
                elif method == "PUT" and not req_body:
                    if base_entity.lower() == "user":
                        req_body = {
                            "name": "Rohan Sharma",
                            "email": "rohan.updated@gmail.com"
                        }
                    else:
                        req_body = {
                            f"{base_entity.lower()}Name": f"Updated {base_entity}",
                            "status": "MODIFIED"
                        }

                # Ensure expected response spec & assertions
                res_spec = tc.get("expected_response_spec") or {}
                status_code = res_spec.get("status_code") or (201 if method == "POST" else 200)
                status_source = res_spec.get("status_source") or ("CONTRACT_SPECIFIED" if contract_has_status else "AI_ASSUMPTION")
                status_note = res_spec.get("status_note") or (f"Status {status_code} verified in API contract" if status_source == "CONTRACT_SPECIFIED" else f"Not specified in API contract (AI assumption: {status_code} — review required)")

                res_body = res_spec.get("response_body")
                if not res_body:
                    if status_code in (200, 201):
                        res_body = {
                            "id": 1,
                            **(req_body if isinstance(req_body, dict) else {}),
                            "createdAt": "2026-08-24T12:00:00Z",
                            "updatedAt": "2026-08-24T12:00:00Z"
                        }
                    else:
                        res_body = {
                            "error": "Validation Error",
                            "message": tc.get("description", "Invalid request parameters"),
                            "statusCode": status_code
                        }

                assertions = res_spec.get("assertions")
                if not assertions:
                    if status_code in (200, 201):
                        assertions = [
                            f"{base_entity} created successfully" if method == "POST" else f"{base_entity} processed successfully",
                            "ID generated (not null)",
                            f"Response payload matches request parameters",
                            "Timestamps populated (createdAt, updatedAt)"
                        ]
                        if base_entity.lower() == "user":
                            assertions.append("Password NOT returned in response")
                    else:
                        assertions = [
                            f"Request rejected with status {status_code}",
                            "Validation error details present in response",
                            "No database mutation performed"
                        ]

                # Ensure layered call chain
                resp_funcs = tc.get("responsible_functions")
                if not resp_funcs or len(resp_funcs) < 2:
                    action_name = "createUser" if method == "POST" else "updateUser" if method == "PUT" else "deleteUser" if method == "DELETE" else "getUserById"
                    resp_funcs = [
                        f"{base_entity}Controller.{action_name}()",
                        f"{base_entity}Service.{action_name}()",
                        f"{base_entity}Repository.{'save()' if method in ('POST', 'PUT') else 'deleteById()' if method == 'DELETE' else 'findById()'}"
                    ]

                normalized.append({
                    "test_key": tc.get("test_key") or f"TC-{idx:03d}",
                    "scenario_type": tc.get("scenario_type", "positive"),
                    "title": tc.get("title", f"Test {idx}"),
                    "description": tc.get("description", ""),
                    "story_reference": story_ref,
                    "request_spec": {
                        "method": method,
                        "endpoint": endpoint,
                        "headers": {"Content-Type": "application/json"},
                        "body": req_body
                    },
                    "expected_response_spec": {
                        "status_code": status_code,
                        "status_source": status_source,
                        "status_note": status_note,
                        "response_body": res_body,
                        "assertions": assertions
                    },
                    "expected_result": tc.get("expected_result") or f"API returns HTTP {status_code} with expected JSON schema",
                    "priority": tc.get("priority", "high"),
                    "risk": tc.get("risk", "medium"),
                    "responsible_functions": resp_funcs
                })
            return normalized

        # Fallback: derive test cases, request/response specs, story references, and layered functions
        derived = []
        idx = 1
        is_auth_story = any(kw in f"{story.get('title', '')} {story.get('description', '')}".lower() for kw in ("jwt", "auth", "login", "register", "token", "security"))

        for scenario_type, scenarios in scenario_map:
            for sc_idx, sc in enumerate(scenarios if scenarios else []):
                desc = sc.get("desc", scenario_type) if isinstance(sc, dict) else str(sc)
                desc_lower = desc.lower()
                
                # Determine HTTP method and endpoint
                method = "GET"
                endpoint = f"/api/{base_entity.lower()}s"

                if is_auth_story:
                    if any(kw in desc_lower for kw in ("register", "signup", "create user")):
                        method = "POST"
                        endpoint = "/api/auth/register"
                    elif any(kw in desc_lower for kw in ("login", "authenticate", "credential")):
                        method = "POST"
                        endpoint = "/api/auth/login"
                    elif any(kw in desc_lower for kw in ("without jwt", "unauthorized", "missing token", "missing auth", "no jwt")):
                        method = "GET"
                        endpoint = "/api/users/profile"
                    elif any(kw in desc_lower for kw in ("invalid jwt", "tampered", "expired jwt", "expired token")):
                        method = "GET"
                        endpoint = "/api/users/profile"
                    else:
                        method = "POST" if "post" in desc_lower else "GET"
                        endpoint = "/api/auth/verify" if "verify" in desc_lower else "/api/users/profile"
                else:
                    if "create" in desc_lower or "post" in desc_lower or "add" in desc_lower:
                        method = "POST"
                    elif "update" in desc_lower or "put" in desc_lower or "modify" in desc_lower:
                        method = "PUT"
                        endpoint = f"/api/{base_entity.lower()}s/1"
                    elif "delete" in desc_lower:
                        method = "DELETE"
                        endpoint = f"/api/{base_entity.lower()}s/1"
                    elif "by id" in desc_lower or f"get {base_entity.lower()}" in desc_lower:
                        method = "GET"
                        endpoint = f"/api/{base_entity.lower()}s/1"

                # Layered Call Chain: Controller -> Service -> Repository
                if is_auth_story:
                    action_name = "register" if "register" in endpoint else "login" if "login" in endpoint else "validateToken"
                    resp_funcs = [
                        f"AuthController.{action_name}()",
                        f"AuthService.{action_name}()",
                        f"UserRepository.{'save()' if 'register' in endpoint else 'findByEmail()'}"
                    ]
                else:
                    action_name = "createUser" if method == "POST" else "updateUser" if method == "PUT" else "deleteUser" if method == "DELETE" else "getUserById"
                    resp_funcs = [
                        f"{base_entity}Controller.{action_name}()",
                        f"{base_entity}Service.{action_name}()",
                        f"{base_entity}Repository.{'save()' if method in ('POST', 'PUT') else 'deleteById()' if method == 'DELETE' else 'findById()'}"
                    ]

                # AC Mapping
                story_ref = ""
                if acs and sc_idx < len(acs):
                    story_ref = f"AC-{sc_idx+1:02d}: {acs[sc_idx]}"
                else:
                    story_ref = f"AC-{idx:02d}: {desc}"

                # Status code & verification
                if scenario_type == "positive":
                    status_code = 201 if ("register" in endpoint or (method == "POST" and not is_auth_story)) else 200
                elif any(kw in desc_lower for kw in ("without jwt", "unauthorized", "missing", "no jwt")):
                    status_code = 401
                elif any(kw in desc_lower for kw in ("invalid jwt", "tampered", "expired", "forbidden")):
                    status_code = 401 if "jwt" in desc_lower else 403
                elif scenario_type in ("negative", "validation"):
                    status_code = 400
                elif scenario_type == "boundary":
                    status_code = 422
                else:
                    status_code = 500

                status_source = "CONTRACT_SPECIFIED" if contract_has_status else "AI_ASSUMPTION"
                status_note = f"Status {status_code} in API contract" if status_source == "CONTRACT_SPECIFIED" else f"Not specified in API contract (AI assumption: {status_code} — review required)"

                # Request & Response specs
                if is_auth_story:
                    req_body = {
                        "name": "Rohan",
                        "email": "rohan@gmail.com",
                        "password": "Password@123"
                    } if "register" in endpoint else {
                        "email": "rohan@gmail.com",
                        "password": "Password@123"
                    } if "login" in endpoint else None
                    
                    req_headers = {"Content-Type": "application/json"}
                    if "without jwt" not in desc_lower and "missing" not in desc_lower and endpoint == "/api/users/profile":
                        req_headers["Authorization"] = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

                    if status_code in (200, 201):
                        res_body = {
                            "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                            "tokenType": "Bearer",
                            "user": {"id": 1, "email": "rohan@gmail.com", "name": "Rohan"}
                        } if "login" in endpoint else {
                            "id": 1,
                            "email": "rohan@gmail.com",
                            "name": "Rohan",
                            "createdAt": "2026-08-24T12:00:00Z"
                        }
                    else:
                        res_body = {
                            "error": "Unauthorized" if status_code == 401 else "Validation Error",
                            "message": desc,
                            "statusCode": status_code
                        }
                    assertions = [
                        f"Response status code is {status_code}",
                        "JWT token present in response payload" if "login" in endpoint and status_code == 200 else "Hashed password NOT exposed in response",
                        "Security context successfully verified"
                    ] if status_code in (200, 201) else [
                        f"Request rejected with status {status_code}",
                        "Appropriate error response payload returned",
                        "Unauthorized access blocked"
                    ]
                else:
                    req_headers = {"Content-Type": "application/json"}
                    req_body = {
                        "name": "Rohan",
                        "email": "rohan@gmail.com",
                        "password": "Password@123"
                    } if method == "POST" else {
                        "name": "Rohan Sharma",
                        "email": "rohan.updated@gmail.com"
                    } if method == "PUT" else None

                    res_body = {
                        "id": 1,
                        "name": "Rohan",
                        "email": "rohan@gmail.com",
                        "createdAt": "2026-08-24T12:00:00Z",
                        "updatedAt": "2026-08-24T12:00:00Z"
                    } if status_code in (200, 201) else {
                        "error": "Validation Error",
                        "message": desc,
                        "statusCode": status_code
                    }

                    assertions = [
                        f"{base_entity} processed successfully",
                        "ID generated (not null)",
                        "Name matches request ('Rohan')",
                        "Email matches request ('rohan@gmail.com')",
                        "Timestamps populated (createdAt, updatedAt)",
                    ] if status_code in (200, 201) and method == "POST" else [
                        f"Response status is {status_code}",
                        f"Payload conforms to {base_entity} schema",
                        "Database state verified"
                    ]

                derived.append({
                    "test_key": f"TC-{idx:03d}",
                    "scenario_type": scenario_type,
                    "title": f"{scenario_type.title()} — {desc}",
                    "description": desc,
                    "story_reference": story_ref,
                    "request_spec": {
                        "method": method,
                        "endpoint": endpoint,
                        "headers": req_headers,
                        "body": req_body
                    },
                    "expected_response_spec": {
                        "status_code": status_code,
                        "status_source": status_source,
                        "status_note": status_note,
                        "response_body": res_body,
                        "assertions": assertions
                    },
                    "expected_result": self._derive_expected_result(desc, scenario_type),
                    "priority": "high" if scenario_type in ("positive", "negative") else "medium",
                    "risk": "high" if scenario_type in ("negative", "error") else "medium",
                    "responsible_functions": resp_funcs,
                })
                idx += 1

        return derived

    def _format_contracts(self, contracts):
        if not contracts:
            return "No explicit API contracts defined."
        lines = []
        for c in contracts:
            lines.append(f"  - {c.get('method', 'GET')} {c.get('path', '/')} (service: {c.get('service', 'unknown')})")
        return "\n".join(lines)

    def _derive_expected_result(self, desc, scenario_type):
        if scenario_type == "positive":
            return f"Request succeeds with expected status and payload matches schema. {desc}"
        elif scenario_type == "negative":
            return f"Request is rejected with appropriate 4xx status and structured error message. {desc}"
        elif scenario_type == "boundary":
            return f"System handles boundary/limit value gracefully without overflow or corruption. {desc}"
        elif scenario_type == "validation":
            return f"Validation error returned indicating specific invalid field. {desc}"
        elif scenario_type == "error":
            return f"System catches exception and returns safe 5xx error payload. {desc}"
        return f"Behavior conforms to acceptance criteria. {desc}"

    def _get_workspace_summary(self, state):
        ws_path = state.get("workspace_path")
        if not ws_path:
            return ""
        try:
            from app.tools.repository.workspace import GitWorkspace
            project = state.get("project", {})
            if project and project.get("uuid"):
                ws = GitWorkspace(project["uuid"], project.get("git_repo_url", ""))
                return ws.get_source_summary(max_files=10, max_bytes_per_file=3000)
        except Exception as e:
            print(f"[TestGenerator] Could not read workspace source summary: {e}")
        return ""

    def _get_rag_context(self, state, query_text):
        try:
            project = state.get("project", {})
            project_id = project.get("id")
            if not project_id:
                return ""
            from app.rag.retrieval.retriever import get_retriever
            retriever = get_retriever()
            chunks = retriever.retrieve(project_id=project_id, query=query_text, top_k=3)
            if chunks:
                return "\n---\n".join(c.content[:400] for c in chunks[:3])
        except Exception as e:
            print(f"[TestGenerator] RAG retrieval failed: {e}")
        return ""



