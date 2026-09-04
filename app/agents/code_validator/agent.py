import uuid
from app.agents.base import BaseAgent
from app.tools.code_analysis.analyzer import get_analyzer
from app.llm.model_router.router import get_router
from app.repositories.test_repo import save_code_quality_run_with_issues
from app.workflows.state_machine import TRACEABILITY


class CodeValidatorAgent(BaseAgent):
    """Static tools are authoritative; LLM only explains findings."""
    name = "code_validator"

    def run(self, workflow_id, state):
        analyzer = get_analyzer()
        code_units = [t.get("generated_code") for t in state.get("generated_tests", [])]
        analysis = analyzer.analyze(code_units)

        cq_id = save_code_quality_run_with_issues(
            str(uuid.uuid4()), workflow_id,
            "mock" if analysis.is_mock else "sonarqube",
            analysis.score, analysis.passed, analysis.is_mock,
            issues=analysis.issues
        )

        explanation = ""
        if analysis.issues:
            explanation = get_router().generate_text(
                "explanation", prompt=f"Explain these findings: {analysis.issues}").text

        state["code_quality"] = {"score": analysis.score, "passed": analysis.passed,
                                 "issues": analysis.issues, "explanation": explanation,
                                 "is_mock": analysis.is_mock}
        state["current_stage"] = TRACEABILITY
        self._record(workflow_id, "code_validation", tool_name="code_analyzer",
                     output_summary={"score": analysis.score, "passed": analysis.passed})
        return state
