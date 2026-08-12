import uuid
from app.agents.base import BaseAgent
from app.tools.alm.adapter import get_alm_adapter
from app.guardrails.engine import check_alm
from app.repositories.evidence_repo import (approvals_for, set_evidence_status,
                                             find_alm_writeback, latest_evidence_row,
                                             record_alm_writeback)
from app.workflows.state_machine import DONE, ALM_APPROVAL, COMPLETED


class AlmAgent(BaseAgent):
    """Write-back only after approval, with idempotency."""
    name = "alm_agent"

    def run(self, workflow_id, state):
        approved = any(a["stage"] == "ALM_ATTACHMENT" and a["decision"] == "APPROVED"
                       for a in approvals_for(workflow_id))
        evidence_row = latest_evidence_row(workflow_id)
        evidence_key = (evidence_row or {}).get("evidence_key") or state.get("evidence", {}).get("evidence_key", "")
        idempotency_key = f"{workflow_id}:{evidence_key}"

        ok, detail = check_alm(approved, idempotency_key, workflow_id)
        if not ok:
            state["status"] = ALM_APPROVAL
            state.setdefault("errors", []).append({"agent": self.name, "message": detail})
            return state

        existing = find_alm_writeback(idempotency_key)
        if existing and existing["status"] == "SUCCESS":
            state["current_stage"] = DONE
            state["status"] = COMPLETED
            return state

        story = state.get("story", {})
        adapter = get_alm_adapter()
        result = adapter.attach_evidence(story.get("external_key", "UNKNOWN"),
                                         {"evidence_key": evidence_key}, idempotency_key)

        record_alm_writeback(str(uuid.uuid4()), workflow_id, story.get("id"),
                             (evidence_row or {}).get("id"), idempotency_key,
                             result["request_id"], result["external_ref"], result["status"],
                             result["response"], result["is_mock"])

        if evidence_row:
            set_evidence_status(evidence_row.get("uuid"), "ATTACHED")

        state["alm"] = {"external_ref": result["external_ref"], "is_mock": result["is_mock"]}
        state["current_stage"] = DONE
        state["status"] = COMPLETED
        self._record(workflow_id, "alm_attachment", tool_name="alm_adapter",
                     output_summary={"external_ref": result["external_ref"]})
        return state
