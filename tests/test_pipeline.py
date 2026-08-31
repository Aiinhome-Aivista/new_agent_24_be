"""
End-to-end orchestrator pipeline test with the DB layer stubbed. Exercises real agent
logic (requirement analysis, test generation, deterministic execution + validation,
evidence, ALM gating) and verifies the three mandatory human checkpoints.
"""
import pytest
from app.workflows import state_machine as sm


@pytest.fixture
def stub_db(monkeypatch):
    def fake_execute(sql, params=(), return_id=False):
        return 1 if return_id else None

    def fake_query(sql, params=(), fetchone=False):
        return None if fetchone else []

    import app.repositories.workflow_repo as wr
    import app.repositories.test_repo as tr
    import app.repositories.evidence_repo as er
    import app.audit.audit_log as al
    for mod in (wr, tr, er, al):
        monkeypatch.setattr(mod, "execute", fake_execute)
        monkeypatch.setattr(mod, "query", fake_query)


def _initial_state():
    return {
        "current_stage": sm.REQUIREMENT_ANALYSIS, "status": sm.QUEUED,
        "project": {"id": 1, "target_language": "java", "target_framework": "junit5"},
        "story": {"id": 1, "title": "Authorize a card payment",
                  "description": "reserve funds", "external_key": "PAY-101"},
        "acceptance_criteria": [
            "valid card authorizes",
            "expired card rejected",
            "amount exceeds daily limit rejected",
        ],
        "api_contracts": [{"method": "POST", "path": "/api/payments/authorize",
                           "service": "AuthorizationService"}],
        "capabilities": ["Test Generation", "API Execution"],
    }


def test_pipeline_stops_at_test_review(stub_db):
    from app.agents.orchestrator.orchestrator import Orchestrator
    state = Orchestrator().advance("wf-1", _initial_state())
    assert state["current_stage"] == sm.TEST_REVIEW
    assert state["status"] == sm.WAITING_FOR_REVIEW
    assert len(state["generated_tests"]) >= 1


def test_pipeline_runs_execution_and_validation(stub_db):
    from app.agents.orchestrator.orchestrator import Orchestrator
    orch = Orchestrator()
    state = orch.advance("wf-2", _initial_state())
    state = orch.resume("wf-2", state, sm.TEST_REVIEW)
    assert state["current_stage"] == sm.EVIDENCE_REVIEW
    # Deterministic tools produced execution + quality values (not the LLM).
    assert state["execution"]["total"] == len(state["generated_tests"])
    assert state["code_quality"]["score"] > 0


def test_pipeline_reaches_alm_approval(stub_db):
    from app.agents.orchestrator.orchestrator import Orchestrator
    orch = Orchestrator()
    state = orch.advance("wf-3", _initial_state())
    state = orch.resume("wf-3", state, sm.TEST_REVIEW)
    state = orch.resume("wf-3", state, sm.EVIDENCE_REVIEW)
    assert state["current_stage"] == sm.ALM_APPROVAL


def test_requirement_analyzer_flags_missing_ac(stub_db):
    from app.agents.orchestrator.orchestrator import Orchestrator
    st = _initial_state()
    st["acceptance_criteria"] = []   # ambiguous — must not invent
    state = Orchestrator().advance("wf-4", st)
    assert state["status"] == sm.BLOCKED
    assert state.get("clarification_required") is True
