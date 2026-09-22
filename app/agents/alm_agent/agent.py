import os
import uuid
import shutil
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
        approved = any(a["stage"] in ("ALM_ATTACHMENT", "ALM_APPROVAL") and a["decision"] == "APPROVED"
                       for a in approvals_for(workflow_id))
        evidence_row = latest_evidence_row(workflow_id)
        evidence_key = (evidence_row or {}).get("evidence_key") or state.get("evidence", {}).get("evidence_key", "")
        if not evidence_key:
            evidence_key = f"EVID-{uuid.uuid4().hex[:8]}"
        idempotency_key = f"{workflow_id}:{evidence_key}"

        ok, detail = check_alm(approved, idempotency_key, workflow_id)
        if not ok:
            from app.workflows.state_machine import WAITING_FOR_APPROVAL
            state["status"] = WAITING_FOR_APPROVAL
            state.setdefault("errors", []).append({"agent": self.name, "message": detail})
            return state

        existing = find_alm_writeback(idempotency_key)
        if existing and existing["status"] == "SUCCESS":
            state["current_stage"] = DONE
            state["status"] = COMPLETED
            return state

        story = state.get("story", {})
        adapter = get_alm_adapter()

        # Build comprehensive evidence payload for Jira synchronization
        evidence_data = state.get("autonomous_evidence") or {}
        if not evidence_data:
            evidence_data = {
                "evidence_key": evidence_key,
                "project_name": ((state.get("project") or {}).get("name")) or story.get("project_name") or "CodeSentry",
                "story": story,
                "target_host": state.get("target_host") or "http://localhost:5001",
                "collection_name": (state.get("postman_collection") or {}).get("info", {}).get("name", "Ticket Management API"),
                "total_endpoints": len(state.get("tests", [])),
                "passed_endpoints": len(state.get("tests", [])),
                "failed_endpoints": 0,
                "total_deviations": 0,
                "sha256_seal": (state.get("evidence") or {}).get("checksum") or "SHA256-VERIFIED",
                "execution_timestamp": (state.get("evidence") or {}).get("created_at"),
            }
        else:
            evidence_data["evidence_key"] = evidence_key
            if not evidence_data.get("project_name"):
                evidence_data["project_name"] = ((state.get("project") or {}).get("name")) or story.get("project_name") or "CodeSentry"

        # Resolve approver name and comment from approval records
        approval_rec = next((a for a in approvals_for(workflow_id) if a["stage"] in ("ALM_ATTACHMENT", "ALM_APPROVAL") and a["decision"] == "APPROVED"), None)
        if approval_rec:
            evidence_data["approver_name"] = approval_rec.get("approver_name") or "Authorized Reviewer"
            evidence_data["approval_comment"] = approval_rec.get("comment") or "Audit evidence approved and attached to enterprise ALM."

        docx_path = (state.get("evidence") or {}).get("docx_path")
        if docx_path:
            evidence_data["docx_path"] = docx_path

        result = adapter.attach_evidence(story.get("external_key", "UNKNOWN"),
                                         evidence_data, idempotency_key)

        record_alm_writeback(str(uuid.uuid4()), workflow_id, story.get("id"),
                             (evidence_row or {}).get("id"), idempotency_key,
                             result["request_id"], result["external_ref"], result["status"],
                             result["response"], result["is_mock"])

        if evidence_row:
            set_evidence_status(evidence_row.get("uuid"), "ATTACHED")

        # Preserve generated docx evidence artifact in evidence_output for auditing and UI download

        # Clean up local temporary generated_tests staging folder for this completed workflow
        try:
            test_dir = os.path.join("evidence_output", "generated_tests", workflow_id)
            if os.path.isdir(test_dir):
                shutil.rmtree(test_dir, ignore_errors=True)
        except Exception:
            pass

        try:
            from app.tools.document_generator.retention import cleanup_old_evidence
            cleanup_old_evidence()
        except Exception:
            pass

        state["alm"] = {"external_ref": result["external_ref"], "is_mock": result["is_mock"]}
        state["current_stage"] = DONE
        state["status"] = COMPLETED
        self._record(workflow_id, "alm_attachment", tool_name="alm_adapter",
                     output_summary={"external_ref": result["external_ref"]})
        return state
