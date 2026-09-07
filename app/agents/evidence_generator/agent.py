import uuid
from app.agents.base import BaseAgent
from app.tools.document_generator.generator import render_evidence
from app.llm.model_router.router import get_router
from app.repositories.evidence_repo import insert_evidence
from app.repositories.test_repo import list_test_cases
from app.workflows.state_machine import EVIDENCE_REVIEW


class EvidenceGeneratorAgent(BaseAgent):
    """Deterministic rendering of Word, PDF, HTML, and Markdown evidence packages with embedded screenshots."""
    name = "evidence_generator"

    def run(self, workflow_id, state):
        story = state.get("story", {})
        test_cases = list_test_cases(workflow_id) or state.get("generated_tests", [])
        execution = state.get("execution")
        code_quality = state.get("code_quality")

        router = get_router()
        narrative = router.generate_text(
            "evidence_narrative",
            prompt=f"Summarize evidence: exec={execution}, quality={code_quality}",
            system="Never alter or invent execution values.").text

        evidence_key = self.nid("EVID")
        path, checksum = render_evidence(
            evidence_key, story, test_cases,
            {**(execution or {}), "runner": "mock" if (execution or {}).get("is_mock") else "newman"},
            code_quality and {**code_quality, "analyzer": "mock" if code_quality.get("is_mock") else "sonarqube"},
            narrative=narrative,
            workflow_id=workflow_id
        )

        insert_evidence(str(uuid.uuid4()), evidence_key, workflow_id, story.get("id"),
                        "md", path, checksum, [execution.get("run_id")] if execution else [],
                        "v1", {"narrative_model": "router"}, narrative)

        state["evidence"] = {"evidence_key": evidence_key, "file_path": path, "checksum": checksum}
        state["current_stage"] = EVIDENCE_REVIEW  # human checkpoint
        self._record(workflow_id, "evidence_generation", tool_name="document_generator",
                     output_summary={"evidence_key": evidence_key, "formats": ["md", "html", "docx", "pdf"]})
        return state
