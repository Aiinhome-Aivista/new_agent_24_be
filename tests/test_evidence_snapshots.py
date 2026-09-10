import os
import json
import docx
import pytest
from app.tools.document_generator.docx_generator import generate_docx_evidence
from app.tools.document_generator.generator import render_autonomous_evidence_html
from app.agents.api_executor.autonomous_agent import AutonomousApiVerifierAgent


def test_docx_and_html_evidence_snapshots_generation():
    """Verifies that generate_docx_evidence and render_autonomous_evidence_html attach API call snapshots."""
    evidence_data = {
        "evidence_key": "EVID-TEST-SNAP01",
        "traceability_id": "TRC-TEST-12345",
        "story": {
            "external_key": "STORY-101",
            "title": "User Authentication & Profile Access",
        },
        "target_host": "http://localhost:5001",
        "collection_name": "Auth API Test Suite",
        "summary_recommendation": "API partially conforms",
        "decision_status": "Review Required",
        "decision_summary": "1 extra field detected in response payload.",
        "total_endpoints": 2,
        "passed_endpoints": 1,
        "failed_endpoints": 1,
        "total_deviations": 2,
        "execution_timestamp": "2026-09-10T12:00:00Z",
        "sha256_seal": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
        "deviation_summary": {
            "total_deviations": 2,
            "critical": 1,
            "major": 0,
            "minor": 1,
            "deviations": [
                {
                    "type": "EXTRA_FIELD_NOT_IN_STORY",
                    "severity": "minor",
                    "field": "user.role",
                    "expected": "Not declared in User Story / Acceptance Criteria",
                    "actual": "'role': 'admin'",
                    "explanation": "Extra key 'role' with value 'admin' was returned in the API response.",
                    "remediation": "Evaluate whether 'role' should be declared or omitted.",
                    "method": "POST",
                    "url": "http://localhost:5001/api/login",
                    "endpoint": "/api/login",
                    "status_code": 200,
                    "duration_ms": 24,
                    "request_payload": {"username": "manas", "password": "password123"},
                    "response_payload": {"success": True, "user": {"id": 1, "username": "manas", "role": "admin"}},
                },
                {
                    "type": "STATUS_CODE_MISMATCH",
                    "severity": "critical",
                    "field": "HTTP Status",
                    "expected": "HTTP 200",
                    "actual": "HTTP 500",
                    "explanation": "Endpoint GET /api/user returned status 500.",
                    "remediation": "Fix internal server error in user profile service.",
                    "method": "GET",
                    "url": "http://localhost:5001/api/user",
                    "endpoint": "/api/user",
                    "status_code": 500,
                    "duration_ms": 42,
                    "request_payload": None,
                    "response_payload": {"success": False, "error": "Internal Database Error"},
                }
            ],
        },
        "results": [
            {
                "test_key": "TC-01",
                "method": "POST",
                "endpoint": "/api/login",
                "status_code": 200,
                "duration_ms": 24,
                "passed": True,
                "assertions": [{"name": "Status 200", "passed": True}],
            },
            {
                "test_key": "TC-02",
                "method": "GET",
                "endpoint": "/api/user",
                "status_code": 500,
                "duration_ms": 42,
                "passed": False,
                "assertions": [{"name": "Status 200", "passed": False}],
            },
        ],
    }

    out_dir = os.path.join(os.path.dirname(__file__), "..", "evidence_output")
    os.makedirs(out_dir, exist_ok=True)

    # 1. Test Word (.docx) generation with evidence snapshots
    docx_path = generate_docx_evidence(evidence_data, out_dir=out_dir)
    assert os.path.exists(docx_path)
    assert docx_path.endswith(".docx")

    doc = docx.Document(docx_path)
    full_text = "\n".join([p.text for p in doc.paragraphs])
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                full_text += "\n" + cell.text

    assert "3.1 Attached API Call Evidence Snapshots" in full_text
    assert "http://localhost:5001/api/login" in full_text
    assert "REQUEST PAYLOAD (BODY SENT)" in full_text
    assert "password123" in full_text
    assert "admin" in full_text
    assert "http://localhost:5001/api/user" in full_text
    assert "Internal Database Error" in full_text

    assert "4.1 Comprehensive Test Execution Evidence Snapshots (All Cases)" in full_text
    assert "TEST CASE #1" in full_text
    assert "TEST CASE #2" in full_text

    # 2. Test HTML/PDF report generation with evidence snapshots
    html_path = render_autonomous_evidence_html(evidence_data, out_dir=out_dir)
    assert os.path.exists(html_path)
    assert html_path.endswith(".html")

    with open(html_path, "r", encoding="utf-8") as f:
        html_text = f.read()

    assert "evidence-snapshot-card" in html_text
    assert "http://localhost:5001/api/login" in html_text
    assert "password123" in html_text
    assert "admin" in html_text
    assert "http://localhost:5001/api/user" in html_text
    assert "Internal Database Error" in html_text
    assert "REQUEST PAYLOAD (BODY SENT)" in html_text
    assert "LIVE CAPTURED SERVER RESPONSE" in html_text
    assert "Comprehensive Test Execution Evidence Snapshots (All Cases)" in html_text


def test_all_successful_cases_evidence_snapshots_generation():
    """Verifies that even when all tests pass (0 anomalies/deviations), full evidence snapshots are attached for every single case in both DOCX and HTML/PDF."""
    success_evidence_data = {
        "evidence_key": "EVID-ALL-PASS-01",
        "traceability_id": "TRC-PASS-99999",
        "story": {
            "external_key": "STORY-200",
            "title": "Clean User Profile & Order Checkout",
        },
        "target_host": "http://localhost:5001",
        "collection_name": "Checkout Suite",
        "summary_recommendation": "API conforms",
        "decision_status": "Ready for Approval",
        "decision_summary": "All test assertions passed and all returned payloads conform strictly to user-story acceptance criteria without anomalies or extraneous data.",
        "total_endpoints": 2,
        "passed_endpoints": 2,
        "failed_endpoints": 0,
        "total_deviations": 0,
        "execution_timestamp": "2026-09-10T12:30:00Z",
        "sha256_seal": "11223344556677889900aabbccddeeff11223344556677889900aabbccddeeff",
        "deviation_summary": {
            "total_deviations": 0,
            "critical": 0,
            "major": 0,
            "minor": 0,
            "deviations": [],
        },
        "results": [
            {
                "test_key": "TC-SUCCESS-01",
                "method": "POST",
                "endpoint": "/api/checkout",
                "url": "http://localhost:5001/api/checkout",
                "status_code": 200,
                "duration_ms": 18,
                "passed": True,
                "assertions": [
                    {"name": "Status is 200 OK", "passed": True},
                    {"name": "Order ID is returned", "passed": True},
                ],
                "deviations": [],
                "request_payload": {"item_id": 42, "quantity": 1, "currency": "USD"},
                "response_payload": {"status": "SUCCESS", "order_id": "ORD-7890", "total_price": 99.50},
            },
            {
                "test_key": "TC-SUCCESS-02",
                "method": "GET",
                "endpoint": "/api/order/ORD-7890",
                "url": "http://localhost:5001/api/order/ORD-7890",
                "status_code": 200,
                "duration_ms": 12,
                "passed": True,
                "assertions": [
                    {"name": "Status is 200 OK", "passed": True},
                    {"name": "Order status is CONFIRMED", "passed": True},
                ],
                "deviations": [],
                "request_payload": None,
                "response_payload": {"order_id": "ORD-7890", "status": "CONFIRMED", "items": [{"id": 42, "qty": 1}]},
            },
        ],
    }

    out_dir = os.path.join(os.path.dirname(__file__), "..", "evidence_output")
    os.makedirs(out_dir, exist_ok=True)

    # 1. Test DOCX generation for 100% successful run
    docx_path = generate_docx_evidence(success_evidence_data, out_dir=out_dir)
    assert os.path.exists(docx_path)
    doc = docx.Document(docx_path)
    full_text = "\n".join([p.text for p in doc.paragraphs])
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                full_text += "\n" + cell.text

    assert "4.1 Comprehensive Test Execution Evidence Snapshots (All Cases)" in full_text
    assert "VERIFIED CONFORMANT" in full_text
    assert "http://localhost:5001/api/checkout" in full_text
    assert "ORD-7890" in full_text
    assert "REQUEST PAYLOAD (BODY SENT)" in full_text
    assert "LIVE CAPTURED RESPONSE (SERVER OBSERVATION)" in full_text
    assert "http://localhost:5001/api/order/ORD-7890" in full_text

    # 2. Test HTML/PDF report generation for 100% successful run
    html_path = render_autonomous_evidence_html(success_evidence_data, out_dir=out_dir)
    assert os.path.exists(html_path)
    with open(html_path, "r", encoding="utf-8") as f:
        html_text = f.read()

    assert "Comprehensive Test Execution Evidence Snapshots (All Cases)" in html_text
    assert "VERIFIED CONFORMANT" in html_text
    assert "http://localhost:5001/api/checkout" in html_text
    assert "ORD-7890" in html_text
    assert "REQUEST PAYLOAD (BODY SENT)" in html_text
    assert "LIVE CAPTURED SERVER RESPONSE (EVIDENCE)" in html_text
    assert "http://localhost:5001/api/order/ORD-7890" in html_text



def test_autonomous_agent_response_validation_logic():
    """Verifies that _validate_response_against_requirements flags extra keys and assertion failures."""
    agent = AutonomousApiVerifierAgent()

    endpoint_item = {
        "path": "/api/login",
        "method": "POST",
        "expected_status_code": 200,
    }
    run_result_item = {
        "status_code": 200,
        "response_body": json.dumps({
            "success": True,
            "access_token": "token_xyz",
            "token_type": "Bearer",
            "user": {
                "id": 1,
                "username": "manas",
                "role": "superadmin"
            }
        }),
        "assertions": [
            {"name": "Status code is 200", "passed": True},
            {"name": "Token returned", "passed": True},
        ]
    }
    expectations = {
        "/api/login": {
            "endpoint": "/api/login",
            "method": "POST",
            "expected_status": 200,
            "required_keys": ["success", "access_token", "token_type", "user"],
            "field_values": {},
            "ac_keys": ["AC-1"],
        }
    }

    devs = agent._validate_response_against_requirements(endpoint_item, run_result_item, expectations)
    assert any(d.get("field") == "user.role" and d.get("type") == "EXTRA_FIELD_NOT_IN_STORY" for d in devs)
