import json
import os
import pytest
from app.auth.security import issue_access
from app.agents.api_executor.autonomous_agent import (
    AutonomousApiVerifierAgent,
    redact_sensitive_data,
    get_cached_hosts,
    add_cached_host,
)
from app.tools.document_generator.docx_generator import generate_docx_evidence
from app.tools.document_generator.generator import render_autonomous_evidence_html


@pytest.fixture
def auth_headers():
    token = issue_access(1, ["ADMIN"], ["*"])
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_collection():
    collection_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "collections", "auth_user_service_collection.json"
    )
    with open(collection_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_secret_redaction_guardrail():
    # Passwords and bearer tokens should be cleanly redacted
    sample_data = {
        "password": "my-secret-password-123",
        "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.signature",
        "user": {
            "client_secret": "top-secret-val",
            "normal_field": "visible",
        }
    }
    redacted = redact_sensitive_data(sample_data)
    assert redacted["password"] == "********"
    assert "REDACTED_JWT_TOKEN" in redacted["authorization"]
    assert redacted["user"]["client_secret"] == "********"
    assert redacted["user"]["normal_field"] == "visible"


def test_host_cache_operations():
    hosts = get_cached_hosts()
    assert len(hosts) >= 1
    updated = add_cached_host("http://localhost:5001", "Auth API")
    assert any(h["url"] == "http://localhost:5001" for h in updated)


def test_autonomous_agent_execution_and_deviation_detection(auth_collection):
    agent = AutonomousApiVerifierAgent(timeout=10)

    # Test live execution against http://localhost:5001
    evidence = agent.execute_autonomous_verification(
        base_url="http://localhost:5001",
        collection_data=auth_collection,
        story_uuid=None,
        is_mock=False,
    )

    assert evidence["total_endpoints"] == 4
    assert evidence["passed_endpoints"] == 4
    assert evidence["failed_endpoints"] == 0

    # Verify detection of the unexpected 'role' field
    assert evidence["total_deviations"] >= 1
    deviations = evidence["deviation_summary"]["deviations"]
    dev_fields = [d["field"] for d in deviations]
    assert any("role" in f for f in dev_fields)

    # Verify recommendation classification
    assert evidence["summary_recommendation"] == "API partially conforms"
    assert evidence["decision_status"] == "Review Required"

    # Verify cryptographic SHA-256 seal
    assert evidence["sha256_seal"] is not None
    assert len(evidence["sha256_seal"]) == 64

    # Verify word (.docx) and html generation
    docx_path = generate_docx_evidence(evidence, out_dir="evidence_output")
    assert os.path.exists(docx_path)
    assert docx_path.endswith(".docx")

    html_path = render_autonomous_evidence_html(evidence, out_dir="evidence_output")
    assert os.path.exists(html_path)


def test_autonomous_run_api_endpoint(client, auth_headers):
    # Test POST /api/v1/api-executor/autonomous-run
    resp = client.post(
        "/api/v1/api-executor/autonomous-run",
        headers=auth_headers,
        json={"base_url": "http://localhost:5001"},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["total_endpoints"] == 4
    assert data["summary_recommendation"] == "API partially conforms"
    assert data["sha256_seal"] is not None

    evidence_key = data["evidence_key"]

    # Test GET /api/v1/api-executor/evidence/<evidence_key>/download-docx
    resp_docx = client.get(f"/api/v1/api-executor/evidence/{evidence_key}/download-docx")
    assert resp_docx.status_code == 200
    assert resp_docx.headers["Content-Type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    # Test GET /api/v1/api-executor/evidence/<evidence_key>/download-json
    resp_json = client.get(f"/api/v1/api-executor/evidence/{evidence_key}/download-json")
    assert resp_json.status_code == 200
    assert resp_json.get_json()["evidence_key"] == evidence_key


def test_alm_writeback_guardrail(client, auth_headers):
    # 1. Unapproved writeback must be rejected by governance guardrail
    resp_blocked = client.post(
        "/api/v1/api-executor/alm-writeback",
        headers=auth_headers,
        json={"evidence_key": "EVID-AUTO-TEST", "human_approved": False},
    )
    assert resp_blocked.status_code == 400
    assert resp_blocked.get_json()["error"]["code"] == "GOVERNANCE_BLOCKED"

    # 2. Approved writeback succeeds
    resp_ok = client.post(
        "/api/v1/api-executor/alm-writeback",
        headers=auth_headers,
        json={
            "evidence_key": "EVID-AUTO-TEST",
            "human_approved": True,
            "approver_name": "QA Lead",
            "approval_comment": "Approved for sprint 1 release.",
        },
    )
    assert resp_ok.status_code == 200
    assert resp_ok.get_json()["data"]["status"] == "SYNCHRONIZED"
    assert "idempotency_key" in resp_ok.get_json()["data"]
