import uuid
import json
from app.agents.base import BaseAgent
from app.llm.model_router.router import get_router
from app.repositories.test_repo import insert_test_case
from app.workflows.state_machine import TEST_REVIEW

_SYSTEM_PROMPT = """You are an expert test engineer generating executable test code.

Given the scenario, API contracts, and project context, generate a complete, compilable
test method. Follow these rules:

1. The test MUST be written in {language} using {framework}.
2. The test MUST validate the specific scenario described.
3. Include proper assertions (not just status code checks — validate response body fields).
4. Include meaningful test method names that reflect the scenario.
5. Add inline comments explaining what each section tests.
6. For negative scenarios, verify error responses and appropriate status codes.
7. For boundary scenarios, test edge values explicitly.

Return ONLY the test code — no explanations, no markdown fences, just compilable code.
"""


class TestGeneratorAgent(BaseAgent):
    name = "test_generator"

    def run(self, workflow_id, state):
        analysis = state.get("analysis", {})
        story = state.get("story", {})
        story_id = story.get("id")
        lang = state.get("project", {}).get("target_language", "java")
        framework = state.get("project", {}).get("target_framework", "junit5")
        contracts = state.get("api_contracts", [])
        service_plan = state.get("service_plan", {})

        # Get RAG context for richer generation
        rag_context = self._get_rag_context(state, story.get("title", ""))

        # Build contract summary for the prompt
        contract_summary = self._format_contracts(contracts)

        router = get_router()

        scenario_map = [("positive", analysis.get("positive_scenarios", [])),
                        ("negative", analysis.get("negative_scenarios", [])),
                        ("boundary", analysis.get("boundary_scenarios", [])),
                        ("validation", analysis.get("validation_scenarios", [])),
                        ("error", analysis.get("error_scenarios", []))]

        generated = []
        idx = 1
        total_latency = 0

        for scenario_type, scenarios in scenario_map:
            for sc in (scenarios if scenarios else []):
                # Build a per-scenario prompt
                sc_desc = sc.get("desc", scenario_type) if isinstance(sc, dict) else str(sc)
                prompt = self._build_prompt(
                    story, sc_desc, scenario_type, contract_summary, rag_context, lang, framework)

                # Generate code for this specific scenario
                code_result = router.generate_code(
                    "test_generation",
                    prompt=prompt,
                    system=_SYSTEM_PROMPT.format(language=lang, framework=framework))

                total_latency += (code_result.latency_ms or 0)

                tc = {
                    "test_key": f"TC-{idx:03d}",
                    "scenario_type": scenario_type,
                    "title": f"{scenario_type.title()} — {sc_desc}",
                    "description": sc_desc,
                    "expected_result": self._derive_expected_result(sc, scenario_type),
                    "priority": self._derive_priority(scenario_type),
                    "risk": "high" if scenario_type in ("negative", "error") else "medium",
                    "origin": "AI_GENERATED",
                    "status": "AWAITING_REVIEW",
                    "generated_code": code_result.text,
                    "target_language": lang,
                    "framework": framework,
                }
                if story_id:
                    insert_test_case(str(uuid.uuid4()), workflow_id, story_id, tc)
                generated.append(tc)
                idx += 1

        # If no scenarios were produced at all, generate a basic test
        if not generated:
            fallback_result = router.generate_code(
                "test_generation",
                prompt=f"Generate a basic {lang}/{framework} smoke test for story: {story.get('title', '')}",
                system=_SYSTEM_PROMPT.format(language=lang, framework=framework))
            tc = {
                "test_key": "TC-001",
                "scenario_type": "positive",
                "title": f"Smoke test — {story.get('title', 'Basic verification')}",
                "description": "Basic smoke test generated as fallback",
                "expected_result": "API responds with expected status code",
                "priority": "high",
                "risk": "medium",
                "origin": "AI_GENERATED",
                "status": "AWAITING_REVIEW",
                "generated_code": fallback_result.text,
                "target_language": lang,
                "framework": framework,
            }
            if story_id:
                insert_test_case(str(uuid.uuid4()), workflow_id, story_id, tc)
            generated.append(tc)
            total_latency += (fallback_result.latency_ms or 0)

        state["generated_tests"] = generated
        state["current_stage"] = TEST_REVIEW  # human checkpoint
        self._record(workflow_id, "test_generation", model_name=f"{lang}/{framework}",
                     latency_ms=total_latency, output_summary={"count": len(generated)})
        return state

    def _build_prompt(self, story, scenario_desc, scenario_type, contract_summary, rag_context, lang, framework):
        """Build a rich per-scenario prompt."""
        prompt = f"""User Story: {story.get('title', '')}
Description: {story.get('description', '')}

Scenario Type: {scenario_type.upper()}
Scenario: {scenario_desc}

API Contracts available:
{contract_summary}
"""
        if rag_context:
            prompt += f"\nProject Knowledge Base Context:\n{rag_context}\n"

        prompt += f"""
Generate a complete {lang} test method using {framework} that tests the above scenario.
The test should:
- Call the appropriate API endpoint from the contracts
- Send the correct request body for a {scenario_type} test
- Assert the expected response status code and body fields
"""
        return prompt

    def _format_contracts(self, contracts):
        """Format API contracts for inclusion in the prompt."""
        if not contracts:
            return "No API contracts available."
        lines = []
        for c in contracts:
            line = f"  - {c.get('method', 'GET')} {c.get('path', '/')} (service: {c.get('service', 'unknown')})"
            lines.append(line)
        return "\n".join(lines)

    def _derive_expected_result(self, scenario, scenario_type):
        """Derive expected result from scenario type."""
        desc = scenario.get("desc", "") if isinstance(scenario, dict) else str(scenario)
        if scenario_type == "positive":
            return f"Request succeeds with 200/201 status. {desc}"
        elif scenario_type == "negative":
            return f"Request is rejected with appropriate error code (400/401/403/422). {desc}"
        elif scenario_type == "boundary":
            return f"System handles edge case correctly. {desc}"
        elif scenario_type == "validation":
            return f"Input validation catches invalid data. {desc}"
        elif scenario_type == "error":
            return f"System returns proper error response. {desc}"
        return f"Behavior matches the acceptance criteria. {desc}"

    def _derive_priority(self, scenario_type):
        """Derive test priority from scenario type."""
        return {
            "positive": "high",
            "negative": "high",
            "boundary": "medium",
            "validation": "medium",
            "error": "high",
        }.get(scenario_type, "medium")

    def _get_rag_context(self, state, query_text):
        """Retrieve relevant knowledge base context for the project."""
        try:
            project = state.get("project", {})
            project_id = project.get("id")
            if not project_id:
                return ""
            from app.rag.retrieval.retriever import get_retriever
            retriever = get_retriever()
            chunks = retriever.retrieve(project_id=project_id, query=query_text, top_k=5)
            if chunks:
                return "\n---\n".join(c.content[:500] for c in chunks[:5])
        except Exception as e:
            print(f"[TestGenerator] RAG retrieval failed: {e}")
        return ""

