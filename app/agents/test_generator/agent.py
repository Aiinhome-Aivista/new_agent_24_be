import uuid
from app.agents.base import BaseAgent
from app.llm.model_router.router import get_router
from app.repositories.test_repo import insert_test_case
from app.workflows.state_machine import TEST_REVIEW


class TestGeneratorAgent(BaseAgent):
    name = "test_generator"

    def run(self, workflow_id, state):
        analysis = state.get("analysis", {})
        story_id = state.get("story", {}).get("id")
        lang = state.get("project", {}).get("target_language", "java")
        framework = state.get("project", {}).get("target_framework", "junit5")

        router = get_router()
        code_result = router.generate_code(
            "test_generation",
            prompt=f"Generate {lang}/{framework} test cases for: {analysis}",
            system="Produce structured, traceable test cases mapped to requirements.")

        scenario_map = [("positive", analysis.get("positive_scenarios", [])),
                        ("negative", analysis.get("negative_scenarios", [])),
                        ("boundary", analysis.get("boundary_scenarios", []))]

        generated = []
        idx = 1
        for scenario_type, scenarios in scenario_map:
            for sc in (scenarios or [{"desc": scenario_type}]):
                tc = {
                    "test_key": f"TC-{idx:03d}",
                    "scenario_type": scenario_type,
                    "title": f"{scenario_type.title()} — {sc.get('desc','scenario')}",
                    "description": sc.get("desc"),
                    "expected_result": "Behavior matches the acceptance criteria.",
                    "priority": "high" if scenario_type == "negative" else "medium",
                    "risk": "medium",
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

        state["generated_tests"] = generated
        state["current_stage"] = TEST_REVIEW  # human checkpoint
        self._record(workflow_id, "test_generation", model_name=code_result.model,
                     latency_ms=code_result.latency_ms, output_summary={"count": len(generated)})
        return state
