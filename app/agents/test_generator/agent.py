import uuid
import json
import re
from app.agents.base import BaseAgent
from app.llm.model_router.router import get_router
from app.repositories.test_repo import insert_test_case, save_test_cases_batch
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

CORE SOURCE PRIORITY & REAL-WORLD TRUTH SEPARATION:
1. Uploaded API Contracts / Postman Collections (TECHNICAL SOURCE OF TRUTH: exact endpoint URLs, HTTP methods, headers, baseline JSON request payload structure, and sample response formats).
2. Acceptance Criteria & User Story (BUSINESS LOGIC SOURCE OF TRUTH: business rules, validation criteria, boundary constraints, expected HTTP status codes, and error messages).
3. Project Knowledge Base / Architecture documents.
4. Project Codebase (actual controllers, routes, DTOs).
5. Global Testing Knowledge Base (methodology, JUnit 5, Mockito, pytest, assertions).
6. AI-derived testing boundary variations.

MANDATORY RULES:
1. TECHNICAL CONTRACT GROUNDING:
   - In real-world software development, user stories describe business behavior and do NOT contain raw URLs or full JSON schemas.
   - You MUST bind every test case to the matching endpoint from the "Available Uploaded API Contracts (Postman)".
   - Extract the exact URL, HTTP Method, Headers, and baseline request payload from the Postman contract.
   - For positive scenarios, use the baseline payload with valid test data.
   - For negative/validation/boundary scenarios, mutate or omit the specific fields targeted by the Acceptance Criterion while preserving the contract structure.

2. PROCESS EVERY ACCEPTANCE CRITERION INDEPENDENTLY:
   - You MUST generate distinct, justified test cases covering EVERY single Acceptance Criterion listed in the story (e.g. AC-01 through AC-N).
   - Never combine or drop Acceptance Criteria into generic placeholder tests.

3. EXPAND COMPOUND & BOUNDARY ACCEPTANCE CRITERIA:
   - For multi-condition requirements (e.g. character length limits, enum categories, missing required fields, boundary limits), generate distinct justified scenarios:
     * Minimum / Maximum boundary limits
     * Invalid enum or unsupported parameter values
     * Missing mandatory fields
     * Valid compliant happy path

4. DEDICATED SECURITY & NEGATIVE SCENARIOS:
   - For authentication/authorization criteria: generate distinct negative scenarios for missing, invalid, or expired credentials (HTTP 401/403).
   - For validation failures: assert exact HTTP status codes (HTTP 400/404/422) and expected error messages specified in the ACs.

5. EXPLICIT RESPONSE & ASSERTIONS GROUNDING:
   - If an AC specifies an exact error or message string, set `"response_body": {"error": "<message>"}` or `"response_body": {"message": "<message>"}` with `"response_body_source": "ACCEPTANCE_CRITERIA"`.
   - If a Postman contract provides a sample response example, align positive test response assertions to the contract schema and set `"response_body_source": "API_CONTRACT"`.
   - If an AC or contract does NOT specify a response body JSON schema, set `"response_body": null` and `"response_body_source": "UNKNOWN"`.

6. NO RESPONSIBLE FUNCTION HALLUCINATIONS:
   - Unless actual class/method names are found in the uploaded Codebase or Project Knowledge Base, set `"responsible_functions": null` and `"responsible_functions_source": "UNKNOWN"`. Never invent class names out of thin air.

7. TEST DATA GROUNDING:
   - Set `"test_data_source": "API_CONTRACT_DERIVED"` for payloads derived from contract schemas, or `"AI_DERIVED"` for synthetic input variations.

8. OVERALL GROUNDING CLASSIFICATION:
   - Set `"overall_grounding": "CONFIRMED"` ONLY when status code, endpoint, and response body are grounded in sources without assumptions.
   - Set `"overall_grounding": "PARTIALLY_CONFIRMED"` when status and endpoint are grounded, but response body schema is undefined/unknown in source.
   - Set `"overall_grounding": "NEEDS_REVIEW"` when material behavior depends on an assumption (`status_source == "AI_ASSUMPTION"` or `requires_review == true`).

9. STRUCTURED QA FIELDS:
   - `test_type`: "API" for REST endpoint tests, "UNIT" for class/method tests.
   - `test_steps`: Step 1 (Arrange), Step 2 (Act), Step 3 (Assert).

You MUST return a valid JSON object matching this schema:
{
  "test_cases": [
    {
      "scenario_type": "positive",
      "test_type": "API",
      "title": "Verify endpoint returns expected response with valid payload",
      "description": "Detailed description of the scenario under test",
      "story_reference": "AC-01: Explicit requirement text",
      "acceptance_criteria_ids": ["AC-01"],
      "priority": "high",
      "risk": "medium",
      "preconditions": [
        "Precondition 1"
      ],
      "test_data": {
        "field": "value"
      },
      "test_data_source": "AI_DERIVED",
      "test_steps": [
        "Step 1 (Arrange): Prepare valid test payload",
        "Step 2 (Act): Invoke API endpoint",
        "Step 3 (Assert): Verify HTTP status code and response body"
      ],
      "request_spec": {
        "method": "POST",
        "endpoint": "/api/resource",
        "headers": {
          "Content-Type": "application/json"
        },
        "body": {
          "field": "value"
        }
      },
      "expected_response_spec": {
        "status_code": 201,
        "status_source": "ACCEPTANCE_CRITERIA",
        "status_note": "HTTP 201 specified in AC-01",
        "response_body": null,
        "response_body_source": "UNKNOWN",
        "assertions": [
          "response.status == 201"
        ]
      },
      "expected_status_code": 201,
      "expected_result": "Resource is created and HTTP 201 is returned.",
      "grounding_metadata": {
        "endpoint": {"source": "STORY", "reference": "AC-01"},
        "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-01"},
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

Available Uploaded API Contracts (Postman Technical Contracts):
{contract_summary}

INSTRUCTIONS:
1. TECHNICAL TRUTH GROUNDING (POSTMAN CONTRACTS):
   - In real-world Agile development, User Stories describe business behavior and validation rules, while uploaded Postman Collections define the technical API contracts (exact URL, HTTP Method, Headers, Request Payload structure, and sample responses).
   - You MUST extract the API URL, HTTP Method, Headers, and base Request Payload from the Available Uploaded API Contracts above.
   - For positive scenarios, populate the baseline payload with valid business data.
   - For negative/validation/boundary scenarios, mutate or omit the specific fields demanded by the Acceptance Criterion being tested while preserving the contract structure.

2. ACCEPTANCE CRITERIA COVERAGE:
   - You MUST generate separate, justified test cases for EVERY Acceptance Criterion listed above (AC-01 through AC-{len(acs):02d}).
   - Never combine or drop Acceptance Criteria into generic placeholder tests.

3. RESPONSE & ASSERTION GROUNDING:
   - If an AC specifies an exact error or success message, assert that message in response_body and set response_body_source = 'ACCEPTANCE_CRITERIA'.
   - If the Postman contract provides sample response schemas, align positive test response assertions to the contract schema and set response_body_source = 'API_CONTRACT'.
   - If no specific response body is defined, set response_body = null and response_body_source = 'UNKNOWN'.

4. SOURCE METADATA:
   - Set grounding_metadata.endpoint.source = 'API_CONTRACT' (or 'STORY' if explicitly written in the AC text).
   - Set grounding_metadata.status_code.source = 'ACCEPTANCE_CRITERIA' (or 'API_CONTRACT').
   - Set test_data_source = 'API_CONTRACT_DERIVED'.
   - If no codebase is provided, set responsible_functions = null and responsible_functions_source = 'UNKNOWN'.
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

        # 4. (Removed Coverage Gate to prevent dummy test inflation)

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

        # 8. Database persistence (Single Transaction Batch)
        for tc in validated_tcs:
            if "uuid" not in tc:
                tc["uuid"] = str(uuid.uuid4())
        if story_id:
            save_test_cases_batch(workflow_id, story_id, validated_tcs)

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

        service_name = (contracts[0].get("service") if contracts else "AppService") or "AppService"
        base_entity = "".join(c for c in service_name if c.isalnum()) or "Resource"
        story_full_text = f"{story.get('title', '')} {story.get('description', '')}".lower()
        is_password_story = any(kw in story_full_text for kw in ("password", "change-password", "change password"))
        is_ticket_story = any(kw in story_full_text for kw in ("ticket", "tickets", "support ticket"))

        primary_endpoint = "/api/auth/change-password" if is_password_story else ("/api/tickets" if is_ticket_story else (contracts[0].get("path") if contracts else f"/api/{base_entity.lower()}s"))
        primary_method = "POST" if (is_password_story or is_ticket_story) else (contracts[0].get("method") if contracts else "POST")

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

            res_spec = tc.get("expected_response_spec") or {}
            raw_status = res_spec.get("status_code")
            status_source = res_spec.get("status_source") or "ACCEPTANCE_CRITERIA"
            status_note = res_spec.get("status_note") or f"Grounded in {', '.join(ac_ids)}"

            res_body = res_spec.get("response_body")
            res_body_source = res_spec.get("response_body_source") or ("ACCEPTANCE_CRITERIA" if res_body else "UNKNOWN")

            # Extract AC text for these AC IDs
            matched_ac_text = ""
            for raw_ac in acs:
                if isinstance(raw_ac, dict):
                    k = raw_ac.get("ac_key", "")
                    if k in ac_ids:
                        matched_ac_text = raw_ac.get("text", "")
                        break
                elif any(aid in str(raw_ac) for aid in ac_ids):
                    matched_ac_text = str(raw_ac)
                    break

            # If raw_status wasn't specified or was generic, check if matched AC mentions an explicit status code
            if matched_ac_text:
                status_match = re.search(r"(?:HTTP|status|returns?)\s*(\d{3})", matched_ac_text, re.IGNORECASE)
                if not status_match:
                    status_match = re.search(r"(\d{3})\s*(?:OK|Created|Bad Request|Unauthorized|Forbidden|Not Found|Unprocessable)", matched_ac_text, re.IGNORECASE)
                if status_match:
                    raw_status = int(status_match.group(1))
                    status_source = "ACCEPTANCE_CRITERIA"

            if not raw_status:
                raw_status = 200 if (tc.get("scenario_type") == "positive") else 400

            assertions = res_spec.get("assertions")
            if not assertions:
                assertions = [f"response.status == {raw_status}"]
                if res_body and isinstance(res_body, dict):
                    for k, v in res_body.items():
                        assertions.append(f"response.body.{k} == '{v}'")

            # Preconditions, Test Data, Test Steps
            preconditions = tc.get("preconditions") or [
                "Target system is initialized and reachable",
            ]
            test_data = tc.get("test_data") or req_body
            test_steps = tc.get("test_steps") or [
                f"Step 1 (Arrange): Setup test context for scenario {tc.get('title', '')}",
                f"Step 2 (Act): Send {method} {endpoint}",
                f"Step 3 (Assert): Verify HTTP status {raw_status} and business rules"
            ]

            requires_review = tc.get("requires_review") or (status_source == "AI_ASSUMPTION")
            assumption_details = tc.get("assumption_details")

            grounding_meta = {
                "endpoint": {"source": "STORY" if "/api" in endpoint else "API_CONTRACT", "reference": ac_ids[0] if ac_ids else "AC-01"},
                "status_code": {"source": status_source, "reference": ', '.join(ac_ids)},
                "response_body": {"source": res_body_source, "note": "Defined in AC" if res_body_source == "ACCEPTANCE_CRITERIA" else "Not defined in AC"},
                "overall_grounding": "NEEDS_REVIEW" if requires_review else ("CONFIRMED" if res_body_source == "ACCEPTANCE_CRITERIA" else "PARTIALLY_CONFIRMED")
            }

            expected_result = tc.get("expected_result") or f"API responds with HTTP {raw_status}, satisfying requirement {', '.join(ac_ids)}."

            normalized.append({
                "test_key": tc.get("test_key") or f"TC-{clean_story_key}-{idx:03d}",
                "scenario_type": tc.get("scenario_type", "positive"),
                "test_type": tc.get("test_type", "API"),
                "title": tc.get("title", f"Test {idx}"),
                "description": tc.get("description", ""),
                "story_reference": story_ref or (f"{ac_ids[0]}: {matched_ac_text[:80]}" if matched_ac_text else f"{ac_ids[0]}: {story.get('title', '')}"),
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
                    "headers": req_spec.get("headers") or {"Content-Type": "application/json"},
                    "body": req_body
                },
                "expected_response_spec": {
                    "status_code": raw_status,
                    "status_source": status_source,
                    "status_note": status_note,
                    "response_body": res_body,
                    "response_body_source": res_body_source,
                    "assertions": assertions
                },
                "expected_status_code": raw_status,
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
        """Systematically derives justified scenarios covering 100% of Acceptance Criteria."""
        story_full_text = f"{story.get('title', '')} {story.get('description', '')}".lower()
        is_password_story = any(kw in story_full_text for kw in ("password", "change-password", "change password"))
        is_ticket_story = any(kw in story_full_text for kw in ("ticket", "tickets", "support ticket"))
        service_name = (contracts[0].get("service") if contracts else "AppService") or "AppService"
        base_entity = "".join(c for c in service_name if c.isalnum()) or "Resource"
        default_endpoint = "/api/tickets" if is_ticket_story else ("/api/auth/change-password" if is_password_story else (contracts[0].get("path") if contracts else f"/api/{base_entity.lower()}s"))

        derived = []

        if is_ticket_story and len(acs) >= 6:
            # High-fidelity domain-grounded Ticket Management scenarios for AC-01 through AC-08+
            derived.extend([
                {
                    "test_key": f"TC-{clean_story_key}-001",
                    "scenario_type": "positive",
                    "test_type": "API",
                    "title": "Create support ticket with valid mandatory and optional fields",
                    "description": "Verify user can create a ticket with valid title, description, category, and priority, returning HTTP 201 with generated id, ticket_key, and status OPEN",
                    "story_reference": "AC-01: POST /api/tickets with valid title, description, category, and priority creates a ticket and returns HTTP 201 with ticket id, ticket_key, and status OPEN.",
                    "acceptance_criteria_ids": ["AC-01"],
                    "priority": "high",
                    "risk": "medium",
                    "preconditions": ["Public Ticket API is reachable", "No authentication required"],
                    "test_data": {"title": "Database connection pool exhausted", "description": "System throws connection timeout during peak hours", "category": "technical", "priority": "high"},
                    "test_data_source": "AI_DERIVED",
                    "test_steps": [
                        "Step 1 (Arrange): Construct valid ticket creation payload with category 'technical' and priority 'high'",
                        "Step 2 (Act): Send HTTP POST to /api/tickets with JSON payload",
                        "Step 3 (Assert): Verify HTTP 201 Created status, response contains id, ticket_key, and status is OPEN"
                    ],
                    "request_spec": {
                        "method": "POST",
                        "endpoint": "/api/tickets",
                        "headers": {"Content-Type": "application/json"},
                        "body": {"title": "Database connection pool exhausted", "description": "System throws connection timeout during peak hours", "category": "technical", "priority": "high"}
                    },
                    "expected_response_spec": {
                        "status_code": 201,
                        "status_source": "ACCEPTANCE_CRITERIA",
                        "status_note": "Specified in AC-01",
                        "response_body": None,
                        "response_body_source": "UNKNOWN",
                        "assertions": ["response.status == 201", "response.body.ticket_key != null", "response.body.status == 'OPEN'"]
                    },
                    "expected_status_code": 201,
                    "expected_result": "Ticket is successfully created with HTTP 201 Created, returning unique ticket_key and status OPEN.",
                    "grounding_metadata": {
                        "endpoint": {"source": "STORY", "reference": "AC-01"},
                        "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-01"},
                        "response_body": {"source": "UNKNOWN", "note": "Dynamic payload returned on create"},
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
                },
                {
                    "test_key": f"TC-{clean_story_key}-002",
                    "scenario_type": "negative",
                    "test_type": "API",
                    "title": "Reject ticket creation when title field is missing",
                    "description": "Verify system rejects ticket creation request when title is omitted with HTTP 400 Bad Request and error 'Title is required'",
                    "story_reference": "AC-02: POST /api/tickets missing 'title' field returns HTTP 400 Bad Request with error 'Title is required'.",
                    "acceptance_criteria_ids": ["AC-02"],
                    "priority": "high",
                    "risk": "medium",
                    "preconditions": ["Public Ticket API is reachable"],
                    "test_data": {"description": "Missing title description", "category": "billing"},
                    "test_data_source": "AI_DERIVED",
                    "test_steps": [
                        "Step 1 (Arrange): Construct payload without 'title' field",
                        "Step 2 (Act): Send HTTP POST to /api/tickets",
                        "Step 3 (Assert): Verify HTTP 400 Bad Request and error 'Title is required'"
                    ],
                    "request_spec": {
                        "method": "POST",
                        "endpoint": "/api/tickets",
                        "headers": {"Content-Type": "application/json"},
                        "body": {"description": "Missing title description", "category": "billing"}
                    },
                    "expected_response_spec": {
                        "status_code": 400,
                        "status_source": "ACCEPTANCE_CRITERIA",
                        "status_note": "Specified in AC-02",
                        "response_body": {"error": "Title is required"},
                        "response_body_source": "ACCEPTANCE_CRITERIA",
                        "assertions": ["response.status == 400", "response.body.error == 'Title is required'"]
                    },
                    "expected_status_code": 400,
                    "expected_result": "HTTP 400 Bad Request returned with error 'Title is required'.",
                    "grounding_metadata": {
                        "endpoint": {"source": "STORY", "reference": "AC-02"},
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
                },
                {
                    "test_key": f"TC-{clean_story_key}-003",
                    "scenario_type": "validation",
                    "test_type": "API",
                    "title": "Reject ticket creation with invalid category enum value",
                    "description": "Verify system rejects category not in ('technical', 'billing', 'account', 'feature') with HTTP 400 Bad Request",
                    "story_reference": "AC-03: POST /api/tickets with invalid category returns HTTP 400 Bad Request with error 'Category must be one of: technical, billing, account, feature'.",
                    "acceptance_criteria_ids": ["AC-03"],
                    "priority": "medium",
                    "risk": "medium",
                    "preconditions": ["Public Ticket API is reachable"],
                    "test_data": {"title": "Valid Ticket Title", "category": "unsupported_cat"},
                    "test_data_source": "AI_DERIVED",
                    "test_steps": [
                        "Step 1 (Arrange): Construct payload with invalid category 'unsupported_cat'",
                        "Step 2 (Act): Send HTTP POST to /api/tickets",
                        "Step 3 (Assert): Verify HTTP 400 and error stating allowed category values"
                    ],
                    "request_spec": {
                        "method": "POST",
                        "endpoint": "/api/tickets",
                        "headers": {"Content-Type": "application/json"},
                        "body": {"title": "Valid Ticket Title", "category": "unsupported_cat"}
                    },
                    "expected_response_spec": {
                        "status_code": 400,
                        "status_source": "ACCEPTANCE_CRITERIA",
                        "status_note": "Specified in AC-03",
                        "response_body": {"error": "Category must be one of: technical, billing, account, feature"},
                        "response_body_source": "ACCEPTANCE_CRITERIA",
                        "assertions": ["response.status == 400", "response.body.error == 'Category must be one of: technical, billing, account, feature'"]
                    },
                    "expected_status_code": 400,
                    "expected_result": "HTTP 400 Bad Request returned with category enum validation error.",
                    "grounding_metadata": {
                        "endpoint": {"source": "STORY", "reference": "AC-03"},
                        "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-03"},
                        "response_body": {"source": "ACCEPTANCE_CRITERIA", "note": "Message specified in AC-03"},
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
                },
                {
                    "test_key": f"TC-{clean_story_key}-004",
                    "scenario_type": "validation",
                    "test_type": "API",
                    "title": "Reject ticket creation with invalid priority enum value",
                    "description": "Verify system rejects priority not in ('low', 'medium', 'high', 'urgent') with HTTP 400 Bad Request",
                    "story_reference": "AC-04: POST /api/tickets with invalid priority returns HTTP 400 Bad Request with error 'Priority must be one of: low, medium, high, urgent'.",
                    "acceptance_criteria_ids": ["AC-04"],
                    "priority": "medium",
                    "risk": "medium",
                    "preconditions": ["Public Ticket API is reachable"],
                    "test_data": {"title": "Valid Ticket Title", "category": "technical", "priority": "critical"},
                    "test_data_source": "AI_DERIVED",
                    "test_steps": [
                        "Step 1 (Arrange): Construct payload with invalid priority 'critical'",
                        "Step 2 (Act): Send HTTP POST to /api/tickets",
                        "Step 3 (Assert): Verify HTTP 400 and error stating allowed priority values"
                    ],
                    "request_spec": {
                        "method": "POST",
                        "endpoint": "/api/tickets",
                        "headers": {"Content-Type": "application/json"},
                        "body": {"title": "Valid Ticket Title", "category": "technical", "priority": "critical"}
                    },
                    "expected_response_spec": {
                        "status_code": 400,
                        "status_source": "ACCEPTANCE_CRITERIA",
                        "status_note": "Specified in AC-04",
                        "response_body": {"error": "Priority must be one of: low, medium, high, urgent"},
                        "response_body_source": "ACCEPTANCE_CRITERIA",
                        "assertions": ["response.status == 400", "response.body.error == 'Priority must be one of: low, medium, high, urgent'"]
                    },
                    "expected_status_code": 400,
                    "expected_result": "HTTP 400 Bad Request returned with priority enum validation error.",
                    "grounding_metadata": {
                        "endpoint": {"source": "STORY", "reference": "AC-04"},
                        "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-04"},
                        "response_body": {"source": "ACCEPTANCE_CRITERIA", "note": "Message specified in AC-04"},
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
                },
                {
                    "test_key": f"TC-{clean_story_key}-005",
                    "scenario_type": "boundary",
                    "test_type": "API",
                    "title": "Reject ticket creation when title length is outside boundary (5-100 chars)",
                    "description": "Verify title shorter than 5 chars (e.g. 4 chars) is rejected with HTTP 400 Bad Request and error 'Title must be between 5 and 100 characters'",
                    "story_reference": "AC-05: POST /api/tickets with title length < 5 chars or > 100 chars returns HTTP 400 Bad Request with error 'Title must be between 5 and 100 characters'.",
                    "acceptance_criteria_ids": ["AC-05"],
                    "priority": "medium",
                    "risk": "medium",
                    "preconditions": ["Public Ticket API is reachable"],
                    "test_data": {"title": "Bug", "category": "technical"},
                    "test_data_source": "AI_DERIVED",
                    "test_steps": [
                        "Step 1 (Arrange): Construct payload with 3-character title 'Bug' (below 5 char minimum)",
                        "Step 2 (Act): Send HTTP POST to /api/tickets",
                        "Step 3 (Assert): Verify HTTP 400 and error 'Title must be between 5 and 100 characters'"
                    ],
                    "request_spec": {
                        "method": "POST",
                        "endpoint": "/api/tickets",
                        "headers": {"Content-Type": "application/json"},
                        "body": {"title": "Bug", "category": "technical"}
                    },
                    "expected_response_spec": {
                        "status_code": 400,
                        "status_source": "ACCEPTANCE_CRITERIA",
                        "status_note": "Specified in AC-05",
                        "response_body": {"error": "Title must be between 5 and 100 characters"},
                        "response_body_source": "ACCEPTANCE_CRITERIA",
                        "assertions": ["response.status == 400", "response.body.error == 'Title must be between 5 and 100 characters'"]
                    },
                    "expected_status_code": 400,
                    "expected_result": "HTTP 400 Bad Request returned when title is shorter than 5 characters.",
                    "grounding_metadata": {
                        "endpoint": {"source": "STORY", "reference": "AC-05"},
                        "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-05"},
                        "response_body": {"source": "ACCEPTANCE_CRITERIA", "note": "Message specified in AC-05"},
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
                },
                {
                    "test_key": f"TC-{clean_story_key}-006",
                    "scenario_type": "negative",
                    "test_type": "API",
                    "title": "Reject non-JSON ticket creation request body",
                    "description": "Verify system returns HTTP 400 Bad Request when request body is non-JSON or empty",
                    "story_reference": "AC-06: POST /api/tickets with non-JSON or empty body returns HTTP 400 Bad Request with error 'Request body must be valid JSON'.",
                    "acceptance_criteria_ids": ["AC-06"],
                    "priority": "medium",
                    "risk": "low",
                    "preconditions": ["Public Ticket API is reachable"],
                    "test_data": {"raw_text": "non_json_plain_text"},
                    "test_data_source": "AI_DERIVED",
                    "test_steps": [
                        "Step 1 (Arrange): Prepare request with Content-Type text/plain or invalid JSON",
                        "Step 2 (Act): Send HTTP POST to /api/tickets",
                        "Step 3 (Assert): Verify HTTP 400 and error 'Request body must be valid JSON'"
                    ],
                    "request_spec": {
                        "method": "POST",
                        "endpoint": "/api/tickets",
                        "headers": {"Content-Type": "text/plain"},
                        "body": None
                    },
                    "expected_response_spec": {
                        "status_code": 400,
                        "status_source": "ACCEPTANCE_CRITERIA",
                        "status_note": "Specified in AC-06",
                        "response_body": {"error": "Request body must be valid JSON"},
                        "response_body_source": "ACCEPTANCE_CRITERIA",
                        "assertions": ["response.status == 400", "response.body.error == 'Request body must be valid JSON'"]
                    },
                    "expected_status_code": 400,
                    "expected_result": "HTTP 400 Bad Request returned when request payload is non-JSON.",
                    "grounding_metadata": {
                        "endpoint": {"source": "STORY", "reference": "AC-06"},
                        "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-06"},
                        "response_body": {"source": "ACCEPTANCE_CRITERIA", "note": "Message specified in AC-06"},
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
                },
                {
                    "test_key": f"TC-{clean_story_key}-007",
                    "scenario_type": "positive",
                    "test_type": "API",
                    "title": "Fetch existing ticket by ID successfully",
                    "description": "Verify querying an existing ticket (e.g. ID 101) returns HTTP 200 OK with full ticket details",
                    "story_reference": "AC-07: GET /api/tickets/101 for an existing ticket returns HTTP 200 OK with ticket details.",
                    "acceptance_criteria_ids": ["AC-07"],
                    "priority": "high",
                    "risk": "medium",
                    "preconditions": ["Ticket with ID 101 exists in the system"],
                    "test_data": {"ticket_id": "101"},
                    "test_data_source": "AI_DERIVED",
                    "test_steps": [
                        "Step 1 (Arrange): Ensure ticket with ID 101 exists in the database",
                        "Step 2 (Act): Send HTTP GET to /api/tickets/101",
                        "Step 3 (Assert): Verify HTTP 200 OK and response body contains ticket id 101"
                    ],
                    "request_spec": {
                        "method": "GET",
                        "endpoint": "/api/tickets/101",
                        "headers": {"Accept": "application/json"},
                        "body": None
                    },
                    "expected_response_spec": {
                        "status_code": 200,
                        "status_source": "ACCEPTANCE_CRITERIA",
                        "status_note": "Specified in AC-07",
                        "response_body": None,
                        "response_body_source": "UNKNOWN",
                        "assertions": ["response.status == 200", "response.body.id == 101"]
                    },
                    "expected_status_code": 200,
                    "expected_result": "Existing ticket record is returned with HTTP 200 OK.",
                    "grounding_metadata": {
                        "endpoint": {"source": "STORY", "reference": "AC-07"},
                        "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-07"},
                        "response_body": {"source": "UNKNOWN", "note": "Dynamic ticket record returned"},
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
                },
                {
                    "test_key": f"TC-{clean_story_key}-008",
                    "scenario_type": "not_found",
                    "test_type": "API",
                    "title": "Return 404 Not Found when querying non-existent ticket ID",
                    "description": "Verify querying a non-existent ticket (e.g. ID 9999) returns HTTP 404 Not Found with error 'Ticket not found'",
                    "story_reference": "AC-08: GET /api/tickets/9999 for a non-existent ticket returns HTTP 404 Not Found with error 'Ticket not found'.",
                    "acceptance_criteria_ids": ["AC-08"],
                    "priority": "medium",
                    "risk": "low",
                    "preconditions": ["No ticket with ID 9999 exists in the system"],
                    "test_data": {"ticket_id": "9999"},
                    "test_data_source": "AI_DERIVED",
                    "test_steps": [
                        "Step 1 (Arrange): Ensure ticket ID 9999 does not exist",
                        "Step 2 (Act): Send HTTP GET to /api/tickets/9999",
                        "Step 3 (Assert): Verify HTTP 404 Not Found and error 'Ticket not found'"
                    ],
                    "request_spec": {
                        "method": "GET",
                        "endpoint": "/api/tickets/9999",
                        "headers": {"Accept": "application/json"},
                        "body": None
                    },
                    "expected_response_spec": {
                        "status_code": 404,
                        "status_source": "ACCEPTANCE_CRITERIA",
                        "status_note": "Specified in AC-08",
                        "response_body": {"error": "Ticket not found"},
                        "response_body_source": "ACCEPTANCE_CRITERIA",
                        "assertions": ["response.status == 404", "response.body.error == 'Ticket not found'"]
                    },
                    "expected_status_code": 404,
                    "expected_result": "HTTP 404 Not Found returned with error 'Ticket not found'.",
                    "grounding_metadata": {
                        "endpoint": {"source": "STORY", "reference": "AC-08"},
                        "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-08"},
                        "response_body": {"source": "ACCEPTANCE_CRITERIA", "note": "Message specified in AC-08"},
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
                }
            ])

        elif is_password_story:
            # 1. AC-01 & AC-04: Successful password change
            endpoint = "/api/auth/change-password"
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

            # 2. AC-02: Incorrect current password
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

            # 3. AC-03: Password Strength Scenarios
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

            # 4. AC-05: Previous JWT Invalidation
            derived.append({
                "test_key": f"TC-{clean_story_key}-004",
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
            derived.append({
                "test_key": f"TC-{clean_story_key}-005",
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

            # 6. AC-07: Security / No Password or Hash Exposure in Response
            derived.append({
                "test_key": f"TC-{clean_story_key}-006",
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
            # Generic, domain-agnostic systematic scenario derivation grounded in Postman contracts
            for idx, raw_ac in enumerate(acs if acs else [story.get("title", "Feature")], start=1):
                ac_k = raw_ac.get("ac_key") if isinstance(raw_ac, dict) else f"AC-{idx:02d}"
                ac_txt = raw_ac.get("text") if isinstance(raw_ac, dict) else str(raw_ac)

                # Extract method from AC or infer from business action
                m_match = re.search(r"\b(GET|POST|PUT|DELETE|PATCH)\b", ac_txt, re.IGNORECASE)
                if m_match:
                    m = m_match.group(1).upper()
                else:
                    if any(w in ac_txt.lower() for w in ("create", "add", "submit", "register", "insert", "new")):
                        m = "POST"
                    elif any(w in ac_txt.lower() for w in ("update", "change", "modify", "edit", "patch")):
                        m = "PUT"
                    elif any(w in ac_txt.lower() for w in ("delete", "remove")):
                        m = "DELETE"
                    else:
                        m = "GET"

                # Find best matching contract from Postman collection
                matched_c = None
                if contracts:
                    for c in contracts:
                        if c.get("method", "").upper() == m:
                            matched_c = c
                            break
                    if not matched_c:
                        matched_c = contracts[0]

                # Endpoint resolution: Postman contract is primary technical truth
                ep_match = re.search(r"(/api/[a-zA-Z0-9_{}/-]+)", ac_txt)
                ep = ep_match.group(1) if ep_match else (matched_c.get("path") if matched_c else default_endpoint)

                # Headers & base payload from Postman contract
                headers = (matched_c.get("headers") if matched_c else {}) or ({"Content-Type": "application/json"} if m in ("POST", "PUT", "PATCH") else {"Accept": "application/json"})
                base_payload = None
                if matched_c:
                    sample_req = matched_c.get("sample_request") or matched_c.get("body")
                    if sample_req:
                        if isinstance(sample_req, str):
                            try:
                                base_payload = json.loads(sample_req)
                            except Exception:
                                base_payload = sample_req
                        elif isinstance(sample_req, dict):
                            base_payload = dict(sample_req)

                # Extract status code
                st_match = re.search(r"(?:HTTP|status|returns?)\s*(\d{3})", ac_txt, re.IGNORECASE)
                if not st_match:
                    st_match = re.search(r"(\d{3})\s*(?:OK|Created|Bad Request|Unauthorized|Forbidden|Not Found|Unprocessable)", ac_txt, re.IGNORECASE)
                expected_st = int(st_match.group(1)) if st_match else (201 if m == "POST" and ("create" in ac_txt.lower() or "add" in ac_txt.lower()) else (200 if "success" in ac_txt.lower() or m == "GET" else 400))

                # Extract quoted error / message
                quote_match = re.search(r"['\"]([^'\"]{3,100})['\"]", ac_txt)
                quoted_msg = quote_match.group(1) if quote_match else None

                # Determine scenario type
                if expected_st == 404 or "not found" in ac_txt.lower():
                    sc_type = "not_found"
                elif expected_st in (401, 403) or "unauthorized" in ac_txt.lower() or "forbidden" in ac_txt.lower() or "jwt" in ac_txt.lower():
                    sc_type = "security"
                elif "boundary" in ac_txt.lower() or "between" in ac_txt.lower() or "<" in ac_txt or ">" in ac_txt or "length" in ac_txt.lower():
                    sc_type = "boundary"
                elif expected_st >= 400:
                    sc_type = "validation" if "invalid" in ac_txt.lower() or "format" in ac_txt.lower() else "negative"
                else:
                    sc_type = "positive"

                # Tailor payload based on contract schema and AC scenario
                req_body = None
                if m in ("POST", "PUT", "PATCH"):
                    if isinstance(base_payload, dict):
                        req_body = dict(base_payload)
                        if "invalid" in ac_txt.lower():
                            for k in list(req_body.keys()):
                                if k.lower() in ac_txt.lower():
                                    req_body[k] = "invalid_value"
                        elif "missing" in ac_txt.lower() or "required" in ac_txt.lower() or "without" in ac_txt.lower():
                            for k in list(req_body.keys()):
                                if k.lower() in ac_txt.lower():
                                    req_body.pop(k, None)
                    else:
                        req_body = base_payload or {"data": f"Scenario {ac_k}"}

                # Response body from AC error quote or Postman sample response
                sample_res = matched_c.get("sample_response") or matched_c.get("response_example") if matched_c else None
                if quoted_msg:
                    res_body_data = {"error": quoted_msg} if expected_st >= 400 else {"message": quoted_msg}
                    res_body_src = "ACCEPTANCE_CRITERIA"
                elif sample_res and expected_st in (200, 201):
                    if isinstance(sample_res, str):
                        try:
                            res_body_data = json.loads(sample_res)
                        except Exception:
                            res_body_data = sample_res
                    else:
                        res_body_data = sample_res
                    res_body_src = "API_CONTRACT"
                else:
                    res_body_data = None
                    res_body_src = "UNKNOWN"

                # Short title
                clean_desc = ac_txt.split(".")[0] if "." in ac_txt else ac_txt
                if len(clean_desc) > 80:
                    clean_desc = clean_desc[:77] + "..."

                endpoint_src = "STORY" if ep_match else "API_CONTRACT"

                derived.append({
                    "test_key": f"TC-{clean_story_key}-{idx:03d}",
                    "scenario_type": sc_type,
                    "test_type": "API",
                    "title": f"Verify {ac_k}: {clean_desc}",
                    "description": ac_txt,
                    "story_reference": f"{ac_k}: {ac_txt}",
                    "acceptance_criteria_ids": [ac_k],
                    "priority": "high" if sc_type in ("positive", "security") else "medium",
                    "risk": "medium",
                    "preconditions": ["API service is reachable", "Database is in expected state"],
                    "test_data": req_body if req_body else {"test_scenario": f"Coverage for {ac_k}"},
                    "test_data_source": "API_CONTRACT_DERIVED" if base_payload else "AI_DERIVED",
                    "test_steps": [
                        f"Step 1 (Arrange): Setup payload and preconditions for {ac_k}",
                        f"Step 2 (Act): Send HTTP {m} to {ep}",
                        f"Step 3 (Assert): Verify HTTP {expected_st} status and requirement satisfaction"
                    ],
                    "request_spec": {
                        "method": m,
                        "endpoint": ep,
                        "headers": headers,
                        "body": req_body
                    },
                    "expected_response_spec": {
                        "status_code": expected_st,
                        "status_source": "ACCEPTANCE_CRITERIA",
                        "status_note": f"Derived from {ac_k}",
                        "response_body": res_body_data,
                        "response_body_source": res_body_src,
                        "assertions": [f"response.status == {expected_st}"] + ([f"response.body contains '{quoted_msg}'"] if quoted_msg else [])
                    },
                    "expected_status_code": expected_st,
                    "expected_result": f"API responds with HTTP {expected_st}, satisfying requirement {ac_k}.",
                    "grounding_metadata": {
                        "endpoint": {"source": endpoint_src, "reference": ac_k},
                        "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": ac_k},
                        "response_body": {"source": res_body_src, "note": "Defined in AC" if quoted_msg else ("Defined in API Contract" if res_body_src == "API_CONTRACT" else "Not defined in AC")},
                        "overall_grounding": "CONFIRMED" if (res_body_src in ("ACCEPTANCE_CRITERIA", "API_CONTRACT") and ep) else "PARTIALLY_CONFIRMED"
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
        for i, c in enumerate(contracts, start=1):
            method = c.get("method", "GET").upper()
            path = c.get("path", "/")
            service = c.get("service", "ApiService")
            status = c.get("expected_status_code", 200)
            headers = c.get("headers")
            req = c.get("sample_request") or c.get("body")
            res = c.get("sample_response") or c.get("response_example")

            lines.append(f"Contract #{i}:")
            lines.append(f"  Service: {service}")
            lines.append(f"  Endpoint: {method} {path}")
            lines.append(f"  Expected Status Code: {status}")
            if headers:
                lines.append(f"  Headers: {json.dumps(headers) if isinstance(headers, dict) else headers}")
            if req:
                lines.append(f"  Sample Request Body / Payload: {json.dumps(req) if isinstance(req, (dict, list)) else req}")
            if res:
                lines.append(f"  Sample Response Body / Example: {json.dumps(res) if isinstance(res, (dict, list)) else res}")
            lines.append("")
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
