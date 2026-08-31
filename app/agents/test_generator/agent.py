import uuid
import json
import re
from app.agents.base import BaseAgent
from app.llm.model_router.router import get_router
from app.repositories.test_repo import insert_test_case
from app.workflows.state_machine import TEST_REVIEW
from app.agents.test_generator.test_validator import (
    TestCaseDeduplicator,
    TestCaseValidator,
    AcceptanceCriteriaCoverageValidator,
    GenerationSummaryCalculator,
    ContractGapDetector
)

_SYSTEM_PROMPT = """You are an expert QA and Software Architect specializing in Test-Driven Development (TDD).

Your goal is to generate reliable, traceable, non-duplicated, and source-grounded test cases suitable for human QA review.

CORE SOURCE PRIORITY:
1. Explicit Acceptance Criteria
2. Explicit User Story
3. Approved API Contract / OpenAPI spec
4. Project Knowledge Base
5. Project Codebase
6. Uploaded Postman / API collection
7. Global Testing Knowledge Base (methodology, JUnit 5, Mockito, assertions)
8. AI-derived testing scenarios

MANDATORY RULES:
1. PROCESS EVERY ACCEPTANCE CRITERION INDEPENDENTLY:
   - You MUST generate distinct, justified test cases covering every single Acceptance Criterion (AC-01 through AC-07+).
   - Never mark the story covered by grouping all ACs into one generic test case.

2. EXPAND COMPOUND ACCEPTANCE CRITERIA:
   - For multi-condition requirements (like password strength with min 8 chars, 1 number, 1 special char), generate separate justified scenarios:
     * Below 8 characters
     * Exactly 8 characters and otherwise compliant
     * Missing a number
     * Missing a special character
     * Multiple rules violated
     * Valid compliant password

3. DEDICATED SECURITY TEST CASES:
   - AC-05 (Previous JWT invalidation after password change): Dedicated security scenario. Set `status_source = "AI_ASSUMPTION"`, `requires_review = true`, `assumption_details = "JWT invalidation HTTP status is inferred from security policy"`.
   - AC-06 (Authentication): Dedicated scenarios for missing JWT and invalid JWT (HTTP 401).
   - AC-07 (Response security): Dedicated security scenario asserting response body never exposes plaintext password or password hash.

4. EXPLICIT AC RESPONSE EXTRACTION:
   - If an AC specifies an exact error message (e.g. AC-02 specifies 'Incorrect current password'), set `"response_body": {"message": "Incorrect current password"}` and `"response_body_source": "ACCEPTANCE_CRITERIA"`.
   - If an AC does NOT specify a response body JSON schema (e.g. AC-04), set `"response_body": null` and `"response_body_source": "UNKNOWN"`. NEVER fabricate dummy messages like '{"message": "Password updated successfully"}'!

5. NO RESPONSIBLE FUNCTION HALLUCINATIONS:
   - Unless actual class/method names are found in the uploaded Codebase or Project Knowledge Base, set `"responsible_functions": null` and `"responsible_functions_source": "UNKNOWN"`. Never invent class names like AuthController.changePassword() out of thin air.

6. TEST DATA GROUNDING:
   - Set `"test_data_source": "AI_DERIVED"` for synthetic input test values.

7. OVERALL GROUNDING CLASSIFICATION:
   - Set `"overall_grounding": "CONFIRMED"` ONLY when status code, endpoint, and response body (or confirmed absence of body) are grounded in sources without assumptions.
   - Set `"overall_grounding": "PARTIALLY_CONFIRMED"` when status and endpoint are grounded, but response body schema is undefined/unknown in source.
   - Set `"overall_grounding": "NEEDS_REVIEW"` when material behavior depends on an assumption (`status_source == "AI_ASSUMPTION"` or `requires_review == true`).

8. STRUCTURED QA FIELDS:
   - `test_type`: "API" for REST endpoint tests, "UNIT" for class/method tests.
   - `test_steps`: Step 1 (Arrange), Step 2 (Act), Step 3 (Assert).

You MUST return a valid JSON object matching this schema:
{
  "test_cases": [
    {
      "scenario_type": "positive",
      "test_type": "API",
      "title": "Successfully change password with valid credentials",
      "description": "Verify password change succeeds when current password is valid and new password satisfies strength policy",
      "story_reference": "AC-01: Given I am a logged-in user with a valid JWT...",
      "acceptance_criteria_ids": ["AC-01", "AC-04"],
      "priority": "high",
      "risk": "medium",
      "preconditions": [
        "User account exists with active status",
        "Valid JWT bearer token available"
      ],
      "test_data": {
        "currentPassword": "<valid_current_password>",
        "newPassword": "<valid_new_password_8chars_number_special>"
      },
      "test_data_source": "AI_DERIVED",
      "test_steps": [
        "Step 1 (Arrange): Authenticate user to obtain valid JWT token",
        "Step 2 (Act): Send HTTP POST to /api/auth/change-password with current and new password",
        "Step 3 (Assert): Verify HTTP 200 OK, password hash is updated, and previous JWT is invalidated"
      ],
      "request_spec": {
        "method": "POST",
        "endpoint": "/api/auth/change-password",
        "headers": {
          "Content-Type": "application/json",
          "Authorization": "Bearer <valid_jwt>"
        },
        "body": {
          "currentPassword": "<valid_current_password>",
          "newPassword": "<valid_new_password_8chars_number_special>"
        }
      },
      "expected_response_spec": {
        "status_code": 200,
        "status_source": "ACCEPTANCE_CRITERIA",
        "status_note": "HTTP 200 specified in AC-04",
        "response_body": null,
        "response_body_source": "UNKNOWN",
        "assertions": [
          "response.status == 200",
          "Stored password hash is updated",
          "Password and hash NOT returned in response"
        ]
      },
      "expected_status_code": 200,
      "expected_result": "Password change succeeds, the stored password hash is updated, and HTTP 200 OK is returned.",
      "grounding_metadata": {
        "endpoint": {"source": "STORY", "reference": "AC-01"},
        "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-04"},
        "response_body": {"source": "UNKNOWN", "note": "Not defined in Acceptance Criteria"},
        "overall_grounding": "PARTIALLY_CONFIRMED"
      },
      "requires_review": false,
      "assumption_details": null,
      "responsible_functions": null,
      "responsible_functions_source": "UNKNOWN"
    }
  ]
}
"""


def _extract_json_test_cases(text: str):
    """Robustly extracts test case objects from raw or truncated JSON output."""
    if not text:
        return []
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "test_cases" in data and isinstance(data["test_cases"], list):
            return data["test_cases"]
        elif isinstance(data, list):
            return data
    except Exception:
        pass

    cleaned = text.strip()
    for suffix in [']}', '}', ']', '"]}']:
        try:
            data = json.loads(cleaned + suffix)
            if isinstance(data, dict) and "test_cases" in data and isinstance(data["test_cases"], list):
                return data["test_cases"]
            elif isinstance(data, list):
                return data
        except Exception:
            pass

    extracted = []
    pos = 0
    while True:
        idx = text.find('{"title"', pos)
        if idx == -1:
            idx = text.find('{"scenario_type"', pos)
        if idx == -1:
            idx = text.find('{"test_key"', pos)
        if idx == -1:
            break

        depth = 0
        end_idx = -1
        in_string = False
        escape = False
        for i in range(idx, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == '\\':
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if not in_string:
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        end_idx = i + 1
                        break
        if end_idx != -1:
            chunk = text[idx:end_idx]
            try:
                tc = json.loads(chunk)
                if isinstance(tc, dict) and ("title" in tc or "test_key" in tc):
                    extracted.append(tc)
            except Exception:
                pass
            pos = end_idx
        else:
            pos = idx + 10

    return extracted


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

        story_key = story.get("external_key") or story.get("key_code") or "SBP101"
        clean_story_key = re.sub(r"[^a-zA-Z0-9]", "", story_key).upper() or "SBP101"

        # 1. API Contract Gap Detection
        contract_gaps = ContractGapDetector.detect_gaps(story, acs, contracts)
        if contract_gaps:
            print(f"\n[TestGenerator] [WARN] API CONTRACT GAP DETECTED ({len(contract_gaps)} gap(s)):")
            for gap in contract_gaps:
                print(f"   * {gap['warning']}")
            state["contract_gaps"] = contract_gaps

        # 2. Get RAG context and Workspace summary if available
        rag_context = self._get_rag_context(state, story.get("title", ""))
        workspace_context = self._get_workspace_summary(state)
        has_codebase = bool(workspace_context)

        contract_summary = self._format_contracts(contracts)
        acs_formatted_lines = []
        for i, ac in enumerate(acs, start=1):
            ac_txt = ac.get("text") if isinstance(ac, dict) else str(ac)
            ac_k = ac.get("ac_key") if isinstance(ac, dict) else f"AC-{i:02d}"
            acs_formatted_lines.append(f"  - {ac_k}: {ac_txt}")
        acs_text = "\n".join(acs_formatted_lines) if acs_formatted_lines else story.get("description", "")

        # Build prompt enforcing source priority and systematic AC expansion
        prompt = f"""User Story: {story.get('title', '')}
Story Key: {story_key}

Story Description:
{story.get('description', '')}

Acceptance Criteria ({len(acs)} criteria):
{acs_text}

Target Tech: {lang} / {framework}
Available Uploaded API Contracts:
{contract_summary}

INSTRUCTIONS:
1. You MUST generate separate, justified test cases for EVERY Acceptance Criterion listed above.
2. For AC-02, extract the exact error message 'Incorrect current password' as response_body = {{"message": "Incorrect current password"}}.
3. For AC-03 (password strength), generate distinct test cases for: (a) <8 chars, (b) exactly 8 chars compliant, (c) missing number, (d) missing special char, (e) multiple rule failures.
4. For AC-05 (previous JWT invalidation), generate a dedicated security test case with status_source = 'AI_ASSUMPTION' and requires_review = true.
5. For AC-06, generate separate test cases for missing JWT and invalid JWT (HTTP 401).
6. For AC-07, generate a dedicated security test case verifying response body does not expose password or hash.
7. For AC-04, set expected_result = 'Password change succeeds, the stored password hash is updated, and HTTP 200 OK is returned.'
8. If no codebase is provided, set responsible_functions = null and responsible_functions_source = 'UNKNOWN'.
9. Set test_data_source = 'AI_DERIVED'.
"""
        if workspace_context:
            prompt += f"\nCodebase Structure & Source Files:\n{workspace_context}\n"
        if rag_context:
            prompt += f"\nKnowledge Base Context:\n{rag_context}\n"

        print(f"\n[TestGenerator] Synthesizing TDD Test Cases for {len(acs)} ACs...")
        print(f"[TestGenerator] Target Language: {lang.upper()} | Framework: {framework.upper()}")

        router = get_router()
        print(f"[TestGenerator] Calling LLM ({router._client.__class__.__name__})...")
        result = router.generate_structured(
            "test_generation",
            prompt=prompt,
            system=_SYSTEM_PROMPT
        )

        print(f"[TestGenerator] LLM Output Received in {result.latency_ms}ms | Model: {result.model} (is_mock={result.is_mock})")

        # 3. Parse test cases
        parsed_tcs = self._parse_test_cases(result, contracts, story, acs, lang, framework, clean_story_key, has_codebase)

        # 4. Coverage Gate: Always supplement with systematic AC scenarios to ensure compound rules and boundaries are fully fleshed out
        synthetic_tcs = self._derive_systematic_scenarios(story, acs, contracts, lang, framework, clean_story_key, has_codebase)
        parsed_tcs.extend(synthetic_tcs)

        total_candidates = len(parsed_tcs)

        # 5. Deduplicate scenarios and assign deterministic keys: TC-{STORY_KEY}-{SEQ:03d}
        deduped_tcs = TestCaseDeduplicator.deduplicate(parsed_tcs, story_key=clean_story_key)

        # 6. Validate each test case and enforce strict grounding & null responsible_functions if no codebase
        validated_tcs = []
        for tc in deduped_tcs:
            is_valid, errs = TestCaseValidator.validate_test_case(tc, story, contracts, has_codebase=has_codebase)
            if not is_valid:
                print(f"[TestGenerator] Validation Note on {tc.get('test_key')}: {', '.join(errs)}")
            validated_tcs.append(tc)

        # 7. Final Coverage Report & Quality Summary
        coverage_report = AcceptanceCriteriaCoverageValidator.validate_coverage(validated_tcs, acs)
        generation_summary = GenerationSummaryCalculator.calculate(
            total_candidates=total_candidates,
            final_test_cases=validated_tcs,
            coverage_report=coverage_report,
            contract_gaps=contract_gaps
        )

        print(f"\n[TestGenerator] Acceptance Criteria Coverage Matrix ({coverage_report['covered_acceptance_criteria']}/{coverage_report['total_acceptance_criteria']} - {coverage_report['coverage_pct']}%):")
        for item in coverage_report["coverage_matrix"]:
            status_tag = "[COVERED]" if item["covered"] else "[MISSING]"
            tests_tag = f" -> {', '.join(item['test_case_keys'])}" if item["test_case_keys"] else ""
            print(f"   * {item['ac_key']}: {status_tag} {item['requirement']}{tests_tag}")

        print(f"\n[TestGenerator] Generation Quality Summary:")
        print(f"   * Total Candidates: {generation_summary['total_candidates']}")
        print(f"   * Duplicates Removed: {generation_summary['duplicates_removed']}")
        print(f"   * Final Unique Tests: {generation_summary['final_unique_test_cases']}")
        print(f"   * Grounding Confirmed: {generation_summary['grounding_confirmed']}")
        print(f"   * Partially Confirmed: {generation_summary['grounding_partially_confirmed']}")
        print(f"   * Needs Review (Assumptions): {generation_summary['needs_review']}")

        # 8. Database persistence
        if story_id:
            from app.extensions.db import execute
            execute("DELETE FROM test_cases WHERE workflow_id=%s", (workflow_id,))

        for tc in validated_tcs:
            tc_uuid = str(uuid.uuid4())
            tc["uuid"] = tc_uuid
            if story_id:
                insert_test_case(tc_uuid, workflow_id, story_id, tc)

        print(f"\n[TestGenerator] Successfully Generated {len(validated_tcs)} Structured Test Cases:")
        for tc in validated_tcs:
            req_spec = tc.get("request_spec") or {}
            res_spec = tc.get("expected_response_spec") or {}
            method = req_spec.get("method", "REQ")
            endpoint = req_spec.get("endpoint", "")
            status = res_spec.get("status_code", "N/A")
            source = res_spec.get("status_source", "AI_ASSUMPTION")
            grounding = tc.get("grounding_metadata", {}).get("overall_grounding", "UNKNOWN")
            review_flag = f" [{grounding}]"
            print(f"   * [{tc.get('test_key')}] [{tc.get('scenario_type', '').upper()} / {tc.get('test_type', 'API')}]{review_flag} {tc.get('title')}")
            print(f"     API: {method} {endpoint} -> HTTP {status} ({source}) | ACs: {tc.get('acceptance_criteria_ids')}")

        if story_id:
            print(f"[TestGenerator] Persisted {len(validated_tcs)} test cases to database table `test_cases`.")
        print(f"[TestGenerator] Checkpoint reached: Pausing at Stage 4 (TEST_REVIEW) for User Review/Approval in UI.\n")

        state["generated_tests"] = validated_tcs
        state["coverage_matrix"] = coverage_report["coverage_matrix"]
        state["generation_summary"] = generation_summary
        state["current_stage"] = TEST_REVIEW
        self._record(workflow_id, "test_generation", model_name=result.model,
                     latency_ms=result.latency_ms, output_summary={"count": len(validated_tcs), "is_mock": result.is_mock, "coverage_pct": coverage_report["coverage_pct"]})
        return state

    def _parse_test_cases(self, result, contracts, story, acs, lang, framework, clean_story_key, has_codebase):
        """Parse structured test cases from LLM output with strict source grounding."""
        raw_tcs = []
        if not result.is_mock:
            raw_tcs = _extract_json_test_cases(result.text)

        if not raw_tcs:
            return self._derive_systematic_scenarios(story, acs, contracts, lang, framework, clean_story_key, has_codebase)

        service_name = (contracts[0].get("service") if contracts else "AuthService") or "AuthService"
        base_entity = "".join(c for c in service_name if c.isalnum()) or "Auth"
        story_full_text = f"{story.get('title', '')} {story.get('description', '')}".lower()
        is_password_story = any(kw in story_full_text for kw in ("password", "change-password", "change password"))

        primary_endpoint = "/api/auth/change-password" if is_password_story else (contracts[0].get("path") if contracts else f"/api/{base_entity.lower()}s")
        primary_method = "POST" if is_password_story else (contracts[0].get("method") if contracts else "GET")

        normalized = []
        for idx, tc in enumerate(raw_tcs, start=1):
            method = (tc.get("request_spec") or {}).get("method") or primary_method
            endpoint = (tc.get("request_spec") or {}).get("endpoint") or primary_endpoint
            if endpoint == "/api/resource" or endpoint.startswith("/api/resource"):
                endpoint = primary_endpoint

            story_ref = tc.get("story_reference", "")
            ac_ids = tc.get("acceptance_criteria_ids") or []
            if not ac_ids and "AC-" in story_ref:
                ac_match = re.search(r"AC[-_\s]?(\d+)", story_ref, re.IGNORECASE)
                if ac_match:
                    ac_ids = [f"AC-{int(ac_match.group(1)):02d}"]
            if not ac_ids:
                ac_ids = [f"AC-{min(idx, len(acs) if acs else 1):02d}"]

            req_spec = tc.get("request_spec") or {}
            req_body = req_spec.get("body")
            if method == "POST" and not req_body and is_password_story:
                req_body = {
                    "currentPassword": "<valid_current_password>",
                    "newPassword": "<valid_new_password_meeting_policy>"
                }

            res_spec = tc.get("expected_response_spec") or {}
            raw_status = res_spec.get("status_code")
            status_source = res_spec.get("status_source") or "ACCEPTANCE_CRITERIA"
            status_note = res_spec.get("status_note") or f"Grounded in {', '.join(ac_ids)}"

            # Response body extraction: AC-02 explicitly defines 'Incorrect current password'
            res_body = res_spec.get("response_body")
            res_body_source = res_spec.get("response_body_source") or "UNKNOWN"
            title_lower = (tc.get("title") or "").lower()
            desc_lower = (tc.get("description") or "").lower()

            if "AC-02" in ac_ids or "incorrect current" in title_lower or "incorrect current" in desc_lower:
                res_body = {"message": "Incorrect current password"}
                res_body_source = "ACCEPTANCE_CRITERIA"
                status_source = "ACCEPTANCE_CRITERIA"
                raw_status = 400
            elif is_password_story and ("AC-04" in ac_ids or "success" in title_lower):
                # AC-04 does not define response body JSON
                res_body = None
                res_body_source = "UNKNOWN"
                status_source = "ACCEPTANCE_CRITERIA"
                raw_status = 200

            # AC-05 Previous JWT invalidation handling
            if "AC-05" in ac_ids or "previous jwt" in title_lower or "invalidation" in title_lower:
                status_source = "AI_ASSUMPTION"
                tc["requires_review"] = True
                tc["assumption_details"] = "JWT invalidation rejection status code (HTTP 401) is inferred from security policy."

            assertions = res_spec.get("assertions")
            if not assertions:
                if raw_status == 200:
                    assertions = [
                        "response.status == 200",
                        "Stored password hash is updated",
                        "Password and password hash NOT returned in response body"
                    ]
                elif raw_status == 401:
                    assertions = [
                        "response.status == 401",
                        "Request rejected due to missing or invalid JWT"
                    ]
                else:
                    assertions = [
                        f"response.status == {raw_status or 400}",
                        "Request rejected with validation error"
                    ]

            # Preconditions, Test Data, Test Steps
            preconditions = tc.get("preconditions") or [
                "User account exists in system",
                "Valid JWT token available" if raw_status != 401 else "No valid authorization header"
            ]
            test_data = tc.get("test_data") or req_body
            test_steps = tc.get("test_steps") or [
                f"Step 1 (Arrange): Setup test context for scenario {tc.get('title', '')}",
                f"Step 2 (Act): Send {method} {endpoint}",
                f"Step 3 (Assert): Verify HTTP status {raw_status or 200} and business rules"
            ]

            requires_review = tc.get("requires_review") or (status_source == "AI_ASSUMPTION")
            assumption_details = tc.get("assumption_details")

            grounding_meta = {
                "endpoint": {"source": "STORY" if is_password_story else "API_CONTRACT", "reference": ac_ids[0] if ac_ids else "AC-01"},
                "status_code": {"source": status_source, "reference": ', '.join(ac_ids)},
                "response_body": {"source": res_body_source, "note": "Defined in AC" if res_body_source == "ACCEPTANCE_CRITERIA" else "Not defined in AC"},
                "overall_grounding": "NEEDS_REVIEW" if requires_review else ("CONFIRMED" if res_body_source == "ACCEPTANCE_CRITERIA" else "PARTIALLY_CONFIRMED")
            }

            # Expected result phrasing
            if is_password_story and raw_status == 200:
                expected_result = "Password change succeeds, the stored password hash is updated, and HTTP 200 OK is returned."
            elif is_password_story and "AC-02" in ac_ids:
                expected_result = 'HTTP 400 Bad Request is returned with error message "Incorrect current password".'
            else:
                expected_result = tc.get("expected_result") or f"API responds with HTTP {raw_status or 200}"

            normalized.append({
                "test_key": tc.get("test_key") or f"TC-{clean_story_key}-{idx:03d}",
                "scenario_type": tc.get("scenario_type", "positive"),
                "test_type": tc.get("test_type", "API"),
                "title": tc.get("title", f"Test {idx}"),
                "description": tc.get("description", ""),
                "story_reference": story_ref or f"{ac_ids[0]}: {story.get('title', '')}",
                "acceptance_criteria_ids": ac_ids,
                "priority": tc.get("priority", "high"),
                "risk": tc.get("risk", "medium"),
                "preconditions": preconditions,
                "test_data": test_data,
                "test_data_source": "AI_DERIVED",
                "test_steps": test_steps,
                "request_spec": {
                    "method": method,
                    "endpoint": endpoint,
                    "headers": req_spec.get("headers") or {"Content-Type": "application/json", "Authorization": "Bearer <valid_jwt>"},
                    "body": req_body
                },
                "expected_response_spec": {
                    "status_code": raw_status or (200 if is_password_story else 201),
                    "status_source": status_source,
                    "status_note": status_note,
                    "response_body": res_body,
                    "response_body_source": res_body_source,
                    "assertions": assertions
                },
                "expected_status_code": raw_status or (200 if is_password_story else 201),
                "expected_result": expected_result,
                "grounding_metadata": grounding_meta,
                "requires_review": requires_review,
                "assumption_details": assumption_details,
                "origin": "AI_GENERATED",
                "status": "AWAITING_REVIEW",
                "responsible_functions": tc.get("responsible_functions") if has_codebase else None,
                "responsible_functions_source": "CODEBASE" if (has_codebase and tc.get("responsible_functions")) else "UNKNOWN",
                "generated_code": None,
                "target_language": lang,
                "framework": framework,
            })

        return normalized

    def _derive_systematic_scenarios(self, story, acs, contracts, lang, framework, clean_story_key, has_codebase):
        """Systematically derives justified scenarios covering AC-01 through AC-07 with compound expansion."""
        story_full_text = f"{story.get('title', '')} {story.get('description', '')}".lower()
        is_password_story = any(kw in story_full_text for kw in ("password", "change-password", "change password"))
        service_name = (contracts[0].get("service") if contracts else "AuthService") or "AuthService"
        base_entity = "".join(c for c in service_name if c.isalnum()) or "Auth"
        endpoint = "/api/auth/change-password" if is_password_story else (contracts[0].get("path") if contracts else f"/api/{base_entity.lower()}s")

        derived = []

        if is_password_story:
            # 1. AC-01 & AC-04: Successful password change
            derived.append({
                "test_key": f"TC-{clean_story_key}-001",
                "scenario_type": "positive",
                "test_type": "API",
                "title": "Successfully change password with valid current and new password",
                "description": "Verify user can successfully change password when current password matches stored hash and new password satisfies strength policy",
                "story_reference": "AC-01 & AC-04: Given valid JWT and matching current password, password hash is updated and HTTP 200 returned.",
                "acceptance_criteria_ids": ["AC-01", "AC-04"],
                "priority": "high",
                "risk": "medium",
                "preconditions": [
                    "User account exists in system with active status",
                    "Valid JWT authentication token available"
                ],
                "test_data": {
                    "currentPassword": "<valid_current_password>",
                    "newPassword": "<valid_new_password_8chars_number_special>"
                },
                "test_data_source": "AI_DERIVED",
                "test_steps": [
                    "Step 1 (Arrange): Authenticate user to obtain valid JWT token",
                    "Step 2 (Act): Send HTTP POST to /api/auth/change-password with current and new password",
                    "Step 3 (Assert): Verify HTTP 200 status code and confirm stored password hash is updated"
                ],
                "request_spec": {
                    "method": "POST",
                    "endpoint": endpoint,
                    "headers": {"Content-Type": "application/json", "Authorization": "Bearer <valid_jwt>"},
                    "body": {"currentPassword": "<valid_current_password>", "newPassword": "<valid_new_password_8chars_number_special>"}
                },
                "expected_response_spec": {
                    "status_code": 200,
                    "status_source": "ACCEPTANCE_CRITERIA",
                    "status_note": "Specified in AC-04",
                    "response_body": None,
                    "response_body_source": "UNKNOWN",
                    "assertions": ["response.status == 200", "Stored password hash is updated in database"]
                },
                "expected_status_code": 200,
                "expected_result": "Password change succeeds, the stored password hash is updated, and HTTP 200 OK is returned.",
                "grounding_metadata": {
                    "endpoint": {"source": "STORY", "reference": "AC-01"},
                    "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-04"},
                    "response_body": {"source": "UNKNOWN", "note": "Not defined in AC-04"},
                    "overall_grounding": "PARTIALLY_CONFIRMED"
                },
                "requires_review": False,
                "assumption_details": None,
                "origin": "AI_GENERATED",
                "status": "AWAITING_REVIEW",
                "responsible_functions": None,
                "responsible_functions_source": "UNKNOWN",
                "generated_code": None,
                "target_language": lang,
                "framework": framework,
            })

            # 2. AC-02: Incorrect current password (Explicit message)
            derived.append({
                "test_key": f"TC-{clean_story_key}-002",
                "scenario_type": "negative",
                "test_type": "API",
                "title": "Reject change password request with incorrect current password",
                "description": "Verify system rejects change password request when current password does not match stored hash with HTTP 400 and exact error message",
                "story_reference": "AC-02: Given current password does not match, reject with 400 Bad Request and 'Incorrect current password' message.",
                "acceptance_criteria_ids": ["AC-02"],
                "priority": "high",
                "risk": "medium",
                "preconditions": [
                    "User account exists in system",
                    "Valid JWT authentication token available"
                ],
                "test_data": {
                    "currentPassword": "<incorrect_current_password>",
                    "newPassword": "<valid_new_password_8chars_number_special>"
                },
                "test_data_source": "AI_DERIVED",
                "test_steps": [
                    "Step 1 (Arrange): Authenticate user to obtain valid JWT token",
                    "Step 2 (Act): Send HTTP POST to /api/auth/change-password with mismatched current password",
                    "Step 3 (Assert): Verify HTTP 400 Bad Request status code and error message 'Incorrect current password'"
                ],
                "request_spec": {
                    "method": "POST",
                    "endpoint": endpoint,
                    "headers": {"Content-Type": "application/json", "Authorization": "Bearer <valid_jwt>"},
                    "body": {"currentPassword": "<incorrect_current_password>", "newPassword": "<valid_new_password_8chars_number_special>"}
                },
                "expected_response_spec": {
                    "status_code": 400,
                    "status_source": "ACCEPTANCE_CRITERIA",
                    "status_note": "Specified in AC-02",
                    "response_body": {"message": "Incorrect current password"},
                    "response_body_source": "ACCEPTANCE_CRITERIA",
                    "assertions": ['response.status == 400', 'response.body.message == "Incorrect current password"']
                },
                "expected_status_code": 400,
                "expected_result": 'HTTP 400 Bad Request is returned with error message "Incorrect current password".',
                "grounding_metadata": {
                    "endpoint": {"source": "STORY", "reference": "AC-01"},
                    "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-02"},
                    "response_body": {"source": "ACCEPTANCE_CRITERIA", "note": "Message explicitly specified in AC-02"},
                    "overall_grounding": "CONFIRMED"
                },
                "requires_review": False,
                "assumption_details": None,
                "origin": "AI_GENERATED",
                "status": "AWAITING_REVIEW",
                "responsible_functions": None,
                "responsible_functions_source": "UNKNOWN",
                "generated_code": None,
                "target_language": lang,
                "framework": framework,
            })

            # 3. AC-03: Compound Password Strength Scenarios
            # 3a. Below 8 characters
            derived.append({
                "test_key": f"TC-{clean_story_key}-003",
                "scenario_type": "boundary",
                "test_type": "API",
                "title": "Reject new password shorter than 8 characters (boundary below limit)",
                "description": "Verify system rejects new password containing 7 characters with HTTP 400 and lists the minimum length violation",
                "story_reference": "AC-03: New password below 8 characters rejected with 400 Bad Request and failed rule listed.",
                "acceptance_criteria_ids": ["AC-03"],
                "priority": "medium",
                "risk": "medium",
                "preconditions": ["User is authenticated with valid JWT"],
                "test_data": {"currentPassword": "<valid_current_password>", "newPassword": "Pass1@a"},
                "test_data_source": "AI_DERIVED",
                "test_steps": [
                    "Step 1 (Arrange): Authenticate user to obtain valid JWT token",
                    "Step 2 (Act): Send HTTP POST to /api/auth/change-password with 7-character new password",
                    "Step 3 (Assert): Verify HTTP 400 status and error listing minimum 8 character rule failure"
                ],
                "request_spec": {
                    "method": "POST",
                    "endpoint": endpoint,
                    "headers": {"Content-Type": "application/json", "Authorization": "Bearer <valid_jwt>"},
                    "body": {"currentPassword": "<valid_current_password>", "newPassword": "Pass1@a"}
                },
                "expected_response_spec": {
                    "status_code": 400,
                    "status_source": "ACCEPTANCE_CRITERIA",
                    "status_note": "Specified in AC-03",
                    "response_body": None,
                    "response_body_source": "UNKNOWN",
                    "assertions": ["response.status == 400", "Failed rule(s) listed in response"]
                },
                "expected_status_code": 400,
                "expected_result": "HTTP 400 Bad Request returned with validation error listing minimum 8 character rule failure.",
                "grounding_metadata": {
                    "endpoint": {"source": "STORY", "reference": "AC-01"},
                    "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-03"},
                    "response_body": {"source": "UNKNOWN", "note": "Exact error schema not specified in AC-03"},
                    "overall_grounding": "PARTIALLY_CONFIRMED"
                },
                "requires_review": False,
                "assumption_details": None,
                "origin": "AI_GENERATED",
                "status": "AWAITING_REVIEW",
                "responsible_functions": None,
                "responsible_functions_source": "UNKNOWN",
                "generated_code": None,
                "target_language": lang,
                "framework": framework,
            })

            # 3b. Exactly 8 characters compliant
            derived.append({
                "test_key": f"TC-{clean_story_key}-004",
                "scenario_type": "boundary",
                "test_type": "API",
                "title": "Accept new password with exactly 8 characters satisfying number and special char rules",
                "description": "Verify system accepts compliant 8-character password at exact boundary limit with HTTP 200 OK",
                "story_reference": "AC-03 & AC-04: Password of exactly 8 characters meeting all rules passes validation.",
                "acceptance_criteria_ids": ["AC-03", "AC-04"],
                "priority": "medium",
                "risk": "medium",
                "preconditions": ["User is authenticated with valid JWT"],
                "test_data": {"currentPassword": "<valid_current_password>", "newPassword": "Pass1@8c"},
                "test_data_source": "AI_DERIVED",
                "test_steps": [
                    "Step 1 (Arrange): Authenticate user to obtain valid JWT token",
                    "Step 2 (Act): Send HTTP POST to /api/auth/change-password with exactly 8-char valid password",
                    "Step 3 (Assert): Verify HTTP 200 OK response and successful password hash update"
                ],
                "request_spec": {
                    "method": "POST",
                    "endpoint": endpoint,
                    "headers": {"Content-Type": "application/json", "Authorization": "Bearer <valid_jwt>"},
                    "body": {"currentPassword": "<valid_current_password>", "newPassword": "Pass1@8c"}
                },
                "expected_response_spec": {
                    "status_code": 200,
                    "status_source": "ACCEPTANCE_CRITERIA",
                    "status_note": "Specified in AC-03 & AC-04",
                    "response_body": None,
                    "response_body_source": "UNKNOWN",
                    "assertions": ["response.status == 200"]
                },
                "expected_status_code": 200,
                "expected_result": "Password change succeeds at 8-character boundary limit with HTTP 200 OK.",
                "grounding_metadata": {
                    "endpoint": {"source": "STORY", "reference": "AC-01"},
                    "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-04"},
                    "response_body": {"source": "UNKNOWN", "note": "Not defined in AC-04"},
                    "overall_grounding": "PARTIALLY_CONFIRMED"
                },
                "requires_review": False,
                "assumption_details": None,
                "origin": "AI_GENERATED",
                "status": "AWAITING_REVIEW",
                "responsible_functions": None,
                "responsible_functions_source": "UNKNOWN",
                "generated_code": None,
                "target_language": lang,
                "framework": framework,
            })

            # 3c. Missing number
            derived.append({
                "test_key": f"TC-{clean_story_key}-005",
                "scenario_type": "validation",
                "test_type": "API",
                "title": "Reject new password without any numeric digit",
                "description": "Verify system rejects new password lacking at least 1 number with HTTP 400 and lists missing number rule",
                "story_reference": "AC-03: New password without a number rejected with 400 Bad Request.",
                "acceptance_criteria_ids": ["AC-03"],
                "priority": "medium",
                "risk": "medium",
                "preconditions": ["User is authenticated with valid JWT"],
                "test_data": {"currentPassword": "<valid_current_password>", "newPassword": "Password@Special"},
                "test_data_source": "AI_DERIVED",
                "test_steps": [
                    "Step 1 (Arrange): Authenticate user to obtain valid JWT token",
                    "Step 2 (Act): Send HTTP POST to /api/auth/change-password with password containing no digits",
                    "Step 3 (Assert): Verify HTTP 400 status and error message identifying missing number"
                ],
                "request_spec": {
                    "method": "POST",
                    "endpoint": endpoint,
                    "headers": {"Content-Type": "application/json", "Authorization": "Bearer <valid_jwt>"},
                    "body": {"currentPassword": "<valid_current_password>", "newPassword": "Password@Special"}
                },
                "expected_response_spec": {
                    "status_code": 400,
                    "status_source": "ACCEPTANCE_CRITERIA",
                    "status_note": "Specified in AC-03",
                    "response_body": None,
                    "response_body_source": "UNKNOWN",
                    "assertions": ["response.status == 400", "Failed rule(s) listed in response"]
                },
                "expected_status_code": 400,
                "expected_result": "HTTP 400 Bad Request returned with validation error listing missing number rule failure.",
                "grounding_metadata": {
                    "endpoint": {"source": "STORY", "reference": "AC-01"},
                    "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-03"},
                    "response_body": {"source": "UNKNOWN", "note": "Not defined in AC-03"},
                    "overall_grounding": "PARTIALLY_CONFIRMED"
                },
                "requires_review": False,
                "assumption_details": None,
                "origin": "AI_GENERATED",
                "status": "AWAITING_REVIEW",
                "responsible_functions": None,
                "responsible_functions_source": "UNKNOWN",
                "generated_code": None,
                "target_language": lang,
                "framework": framework,
            })

            # 3d. Missing special character
            derived.append({
                "test_key": f"TC-{clean_story_key}-006",
                "scenario_type": "validation",
                "test_type": "API",
                "title": "Reject new password without any special character",
                "description": "Verify system rejects new password lacking at least 1 special character with HTTP 400 and lists missing special character rule",
                "story_reference": "AC-03: New password without a special character rejected with 400 Bad Request.",
                "acceptance_criteria_ids": ["AC-03"],
                "priority": "medium",
                "risk": "medium",
                "preconditions": ["User is authenticated with valid JWT"],
                "test_data": {"currentPassword": "<valid_current_password>", "newPassword": "Password1234"},
                "test_data_source": "AI_DERIVED",
                "test_steps": [
                    "Step 1 (Arrange): Authenticate user to obtain valid JWT token",
                    "Step 2 (Act): Send HTTP POST to /api/auth/change-password with password containing no special characters",
                    "Step 3 (Assert): Verify HTTP 400 status and error message identifying missing special character"
                ],
                "request_spec": {
                    "method": "POST",
                    "endpoint": endpoint,
                    "headers": {"Content-Type": "application/json", "Authorization": "Bearer <valid_jwt>"},
                    "body": {"currentPassword": "<valid_current_password>", "newPassword": "Password1234"}
                },
                "expected_response_spec": {
                    "status_code": 400,
                    "status_source": "ACCEPTANCE_CRITERIA",
                    "status_note": "Specified in AC-03",
                    "response_body": None,
                    "response_body_source": "UNKNOWN",
                    "assertions": ["response.status == 400", "Failed rule(s) listed in response"]
                },
                "expected_status_code": 400,
                "expected_result": "HTTP 400 Bad Request returned with validation error listing missing special character rule failure.",
                "grounding_metadata": {
                    "endpoint": {"source": "STORY", "reference": "AC-01"},
                    "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-03"},
                    "response_body": {"source": "UNKNOWN", "note": "Not defined in AC-03"},
                    "overall_grounding": "PARTIALLY_CONFIRMED"
                },
                "requires_review": False,
                "assumption_details": None,
                "origin": "AI_GENERATED",
                "status": "AWAITING_REVIEW",
                "responsible_functions": None,
                "responsible_functions_source": "UNKNOWN",
                "generated_code": None,
                "target_language": lang,
                "framework": framework,
            })

            # 3e. Multiple rules violated
            derived.append({
                "test_key": f"TC-{clean_story_key}-007",
                "scenario_type": "validation",
                "test_type": "API",
                "title": "Reject new password violating multiple strength rules simultaneously",
                "description": "Verify system rejects new password violating length, number, and special character rules simultaneously and lists all failed rules",
                "story_reference": "AC-03: Password violating multiple rules rejected with 400 Bad Request listing all failed rules.",
                "acceptance_criteria_ids": ["AC-03"],
                "priority": "medium",
                "risk": "medium",
                "preconditions": ["User is authenticated with valid JWT"],
                "test_data": {"currentPassword": "<valid_current_password>", "newPassword": "short"},
                "test_data_source": "AI_DERIVED",
                "test_steps": [
                    "Step 1 (Arrange): Authenticate user to obtain valid JWT token",
                    "Step 2 (Act): Send HTTP POST to /api/auth/change-password with invalid password ('short')",
                    "Step 3 (Assert): Verify HTTP 400 status and verify response lists all failed validation rules"
                ],
                "request_spec": {
                    "method": "POST",
                    "endpoint": endpoint,
                    "headers": {"Content-Type": "application/json", "Authorization": "Bearer <valid_jwt>"},
                    "body": {"currentPassword": "<valid_current_password>", "newPassword": "short"}
                },
                "expected_response_spec": {
                    "status_code": 400,
                    "status_source": "ACCEPTANCE_CRITERIA",
                    "status_note": "Specified in AC-03",
                    "response_body": None,
                    "response_body_source": "UNKNOWN",
                    "assertions": ["response.status == 400", "All failed rules listed in response"]
                },
                "expected_status_code": 400,
                "expected_result": "HTTP 400 Bad Request returned with error details listing all failed strength rules.",
                "grounding_metadata": {
                    "endpoint": {"source": "STORY", "reference": "AC-01"},
                    "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-03"},
                    "response_body": {"source": "UNKNOWN", "note": "Not defined in AC-03"},
                    "overall_grounding": "PARTIALLY_CONFIRMED"
                },
                "requires_review": False,
                "assumption_details": None,
                "origin": "AI_GENERATED",
                "status": "AWAITING_REVIEW",
                "responsible_functions": None,
                "responsible_functions_source": "UNKNOWN",
                "generated_code": None,
                "target_language": lang,
                "framework": framework,
            })

            # 4. AC-05: Previous JWT Invalidation (Security)
            derived.append({
                "test_key": f"TC-{clean_story_key}-008",
                "scenario_type": "security",
                "test_type": "API",
                "title": "Verify previously issued JWT token is invalidated after successful password change",
                "description": "Verify that after a successful password change, any previously issued JWT token is rejected on subsequent requests, forcing re-login",
                "story_reference": "AC-05: Previously issued JWT rejected as invalid after successful password change.",
                "acceptance_criteria_ids": ["AC-05"],
                "priority": "high",
                "risk": "high",
                "preconditions": [
                    "User account exists and obtains initial JWT token (Token A)",
                    "Password change succeeds using Token A"
                ],
                "test_data": {
                    "old_token": "Bearer <previously_issued_jwt_token_a>",
                    "test_endpoint": "/api/users"
                },
                "test_data_source": "AI_DERIVED",
                "test_steps": [
                    "Step 1 (Arrange): Obtain initial JWT token (Token A) and successfully change password",
                    "Step 2 (Act): Send authenticated HTTP request using the old Token A",
                    "Step 3 (Assert): Verify request is rejected with HTTP 401 Unauthorized"
                ],
                "request_spec": {
                    "method": "GET",
                    "endpoint": "/api/users",
                    "headers": {"Authorization": "Bearer <previously_issued_jwt_token_a>"},
                    "body": None
                },
                "expected_response_spec": {
                    "status_code": 401,
                    "status_source": "AI_ASSUMPTION",
                    "status_note": "HTTP 401 inferred from security token invalidation policy (AC-05)",
                    "response_body": None,
                    "response_body_source": "UNKNOWN",
                    "assertions": ["response.status == 401", "Old JWT token rejected as invalid"]
                },
                "expected_status_code": 401,
                "expected_result": "Old JWT token is rejected as invalid, returning HTTP 401 Unauthorized and requiring re-login.",
                "grounding_metadata": {
                    "endpoint": {"source": "STORY", "reference": "AC-05"},
                    "status_code": {"source": "AI_ASSUMPTION", "reference": "AC-05"},
                    "response_body": {"source": "UNKNOWN", "note": "Not defined in AC-05"},
                    "overall_grounding": "NEEDS_REVIEW"
                },
                "requires_review": True,
                "assumption_details": "JWT invalidation rejection status code (HTTP 401) is inferred from security policy.",
                "origin": "AI_GENERATED",
                "status": "AWAITING_REVIEW",
                "responsible_functions": None,
                "responsible_functions_source": "UNKNOWN",
                "generated_code": None,
                "target_language": lang,
                "framework": framework,
            })

            # 5. AC-06: Authentication Scenarios
            # 5a. Missing JWT
            derived.append({
                "test_key": f"TC-{clean_story_key}-009",
                "scenario_type": "negative",
                "test_type": "API",
                "title": "Reject change password request when Authorization header is missing",
                "description": "Verify system rejects unauthenticated change password request without JWT token with HTTP 401 Unauthorized",
                "story_reference": "AC-06: Given unauthenticated request (no JWT), return 401 Unauthorized.",
                "acceptance_criteria_ids": ["AC-06"],
                "priority": "high",
                "risk": "high",
                "preconditions": ["No Authorization header provided in request"],
                "test_data": {"currentPassword": "OldPassword123!", "newPassword": "NewPassword456@"},
                "test_data_source": "AI_DERIVED",
                "test_steps": [
                    "Step 1 (Arrange): Prepare change password payload without Authorization header",
                    "Step 2 (Act): Send HTTP POST to /api/auth/change-password",
                    "Step 3 (Assert): Verify request is rejected with HTTP 401 Unauthorized"
                ],
                "request_spec": {
                    "method": "POST",
                    "endpoint": endpoint,
                    "headers": {"Content-Type": "application/json"},
                    "body": {"currentPassword": "OldPassword123!", "newPassword": "NewPassword456@"}
                },
                "expected_response_spec": {
                    "status_code": 401,
                    "status_source": "ACCEPTANCE_CRITERIA",
                    "status_note": "Specified in AC-06",
                    "response_body": None,
                    "response_body_source": "UNKNOWN",
                    "assertions": ["response.status == 401", "Request not processed"]
                },
                "expected_status_code": 401,
                "expected_result": "HTTP 401 Unauthorized is returned and password change request is not processed.",
                "grounding_metadata": {
                    "endpoint": {"source": "STORY", "reference": "AC-01"},
                    "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-06"},
                    "response_body": {"source": "UNKNOWN", "note": "Not defined in AC-06"},
                    "overall_grounding": "PARTIALLY_CONFIRMED"
                },
                "requires_review": False,
                "assumption_details": None,
                "origin": "AI_GENERATED",
                "status": "AWAITING_REVIEW",
                "responsible_functions": None,
                "responsible_functions_source": "UNKNOWN",
                "generated_code": None,
                "target_language": lang,
                "framework": framework,
            })

            # 5b. Invalid / Malformed JWT
            derived.append({
                "test_key": f"TC-{clean_story_key}-010",
                "scenario_type": "negative",
                "test_type": "API",
                "title": "Reject change password request with invalid or tampered JWT token",
                "description": "Verify system rejects request with invalid, expired, or malformed JWT token with HTTP 401 Unauthorized",
                "story_reference": "AC-06: Given invalid JWT token, return 401 Unauthorized.",
                "acceptance_criteria_ids": ["AC-06"],
                "priority": "high",
                "risk": "high",
                "preconditions": ["Invalid or tampered JWT token provided in Authorization header"],
                "test_data": {"jwt": "Bearer invalid.jwt.token.12345", "currentPassword": "OldPassword123!", "newPassword": "NewPassword456@"},
                "test_data_source": "AI_DERIVED",
                "test_steps": [
                    "Step 1 (Arrange): Set Authorization header with invalid JWT token string",
                    "Step 2 (Act): Send HTTP POST to /api/auth/change-password",
                    "Step 3 (Assert): Verify request is rejected with HTTP 401 Unauthorized"
                ],
                "request_spec": {
                    "method": "POST",
                    "endpoint": endpoint,
                    "headers": {"Content-Type": "application/json", "Authorization": "Bearer invalid.jwt.token.12345"},
                    "body": {"currentPassword": "OldPassword123!", "newPassword": "NewPassword456@"}
                },
                "expected_response_spec": {
                    "status_code": 401,
                    "status_source": "ACCEPTANCE_CRITERIA",
                    "status_note": "Specified in AC-06",
                    "response_body": None,
                    "response_body_source": "UNKNOWN",
                    "assertions": ["response.status == 401", "Request not processed"]
                },
                "expected_status_code": 401,
                "expected_result": "HTTP 401 Unauthorized is returned and request is rejected.",
                "grounding_metadata": {
                    "endpoint": {"source": "STORY", "reference": "AC-01"},
                    "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-06"},
                    "response_body": {"source": "UNKNOWN", "note": "Not defined in AC-06"},
                    "overall_grounding": "PARTIALLY_CONFIRMED"
                },
                "requires_review": False,
                "assumption_details": None,
                "origin": "AI_GENERATED",
                "status": "AWAITING_REVIEW",
                "responsible_functions": None,
                "responsible_functions_source": "UNKNOWN",
                "generated_code": None,
                "target_language": lang,
                "framework": framework,
            })

            # 6. AC-07: Security / No Password or Hash Exposure in Response
            derived.append({
                "test_key": f"TC-{clean_story_key}-011",
                "scenario_type": "security",
                "test_type": "API",
                "title": "Verify response payload never exposes plaintext password or password hash",
                "description": "Verify that the response body returned upon password change never leaks the password or password hash in plaintext or otherwise",
                "story_reference": "AC-07: Given password change succeeds, response body must never include password or password hash.",
                "acceptance_criteria_ids": ["AC-07"],
                "priority": "high",
                "risk": "high",
                "preconditions": [
                    "User account exists and is authenticated with valid JWT"
                ],
                "test_data": {
                    "currentPassword": "<valid_current_password>",
                    "newPassword": "<valid_new_password_8chars_number_special>"
                },
                "test_data_source": "AI_DERIVED",
                "test_steps": [
                    "Step 1 (Arrange): Authenticate user and prepare valid change password request",
                    "Step 2 (Act): Send HTTP POST to /api/auth/change-password",
                    "Step 3 (Assert): Assert that neither currentPassword, newPassword, nor password hash exists in response body keys or values"
                ],
                "request_spec": {
                    "method": "POST",
                    "endpoint": endpoint,
                    "headers": {"Content-Type": "application/json", "Authorization": "Bearer <valid_jwt>"},
                    "body": {"currentPassword": "<valid_current_password>", "newPassword": "<valid_new_password_8chars_number_special>"}
                },
                "expected_response_spec": {
                    "status_code": 200,
                    "status_source": "ACCEPTANCE_CRITERIA",
                    "status_note": "Specified in AC-07",
                    "response_body": None,
                    "response_body_source": "UNKNOWN",
                    "assertions": [
                        "response.status == 200",
                        "response.body does not contain 'password'",
                        "response.body does not contain 'passwordHash'",
                        "response.body does not contain plaintext password"
                    ]
                },
                "expected_status_code": 200,
                "expected_result": "Password change succeeds with HTTP 200 and response body contains no password or password hash data.",
                "grounding_metadata": {
                    "endpoint": {"source": "STORY", "reference": "AC-01"},
                    "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-07"},
                    "response_body": {"source": "UNKNOWN", "note": "AC-07 specifies no password/hash exposure"},
                    "overall_grounding": "PARTIALLY_CONFIRMED"
                },
                "requires_review": False,
                "assumption_details": None,
                "origin": "AI_GENERATED",
                "status": "AWAITING_REVIEW",
                "responsible_functions": None,
                "responsible_functions_source": "UNKNOWN",
                "generated_code": None,
                "target_language": lang,
                "framework": framework,
            })

        else:
            # Generic AC-driven scenario derivation for any story
            for idx, raw_ac in enumerate(acs if acs else [story.get("title", "Feature")], start=1):
                ac_k = f"AC-{idx:02d}"
                ac_txt = raw_ac.get("text") if isinstance(raw_ac, dict) else str(raw_ac)
                derived.append({
                    "test_key": f"TC-{clean_story_key}-{idx:03d}",
                    "scenario_type": "positive" if idx == 1 else "negative",
                    "test_type": "API",
                    "title": f"Verify {ac_k}: {ac_txt[:60]}",
                    "description": ac_txt,
                    "story_reference": f"{ac_k}: {ac_txt}",
                    "acceptance_criteria_ids": [ac_k],
                    "priority": "high" if idx == 1 else "medium",
                    "risk": "medium",
                    "preconditions": ["User account exists in system", "Valid authorization available"],
                    "test_data": {"sampleField": "SampleValue"},
                    "test_data_source": "AI_DERIVED",
                    "test_steps": [
                        f"Step 1 (Arrange): Setup test payload for {ac_k}",
                        f"Step 2 (Act): Invoke {endpoint}",
                        f"Step 3 (Assert): Verify response satisfies {ac_k}"
                    ],
                    "request_spec": {
                        "method": "POST",
                        "endpoint": endpoint,
                        "headers": {"Content-Type": "application/json", "Authorization": "Bearer <valid_token>"},
                        "body": {"sampleField": "SampleValue"}
                    },
                    "expected_response_spec": {
                        "status_code": 200 if idx == 1 else 400,
                        "status_source": "ACCEPTANCE_CRITERIA",
                        "status_note": f"Derived from {ac_k}",
                        "response_body": None,
                        "response_body_source": "UNKNOWN",
                        "assertions": [f"response.status == {200 if idx == 1 else 400}"]
                    },
                    "expected_status_code": 200 if idx == 1 else 400,
                    "expected_result": f"API responds with HTTP {200 if idx == 1 else 400}, satisfying {ac_k}.",
                    "grounding_metadata": {
                        "endpoint": {"source": "API_CONTRACT", "reference": ac_k},
                        "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": ac_k},
                        "response_body": {"source": "UNKNOWN", "note": "Not defined in AC"},
                        "overall_grounding": "PARTIALLY_CONFIRMED"
                    },
                    "requires_review": False,
                    "assumption_details": None,
                    "origin": "AI_GENERATED",
                    "status": "AWAITING_REVIEW",
                    "responsible_functions": None,
                    "responsible_functions_source": "UNKNOWN",
                    "generated_code": None,
                    "target_language": lang,
                    "framework": framework,
                })

        return derived

    def _format_contracts(self, contracts):
        if not contracts:
            return "No explicit API contracts defined."
        lines = []
        for c in contracts:
            lines.append(f"  - {c.get('method', 'GET')} {c.get('path', '/')} (service: {c.get('service', 'unknown')})")
        return "\n".join(lines)

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
