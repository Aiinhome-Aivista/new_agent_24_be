import os
import docx
import pytest
from app.tools.document_generator.docx_generator import generate_docx_evidence
from app.tools.document_generator.generator import render_autonomous_evidence_html


@pytest.fixture
def evidence_data_with_failed_unit_test():
    """
    Simulates a run where API tests passed 100% (8/8) but 1 User Story Unit Test failed (8/9 passed, 1 failed).
    This matches the real edge condition described in prompt.md.
    """
    return {
        "evidence_key": "EVID-TEST-CONSISTENCY-01",
        "traceability_id": "TRC-CONSISTENCY-001",
        "story": {
            "external_key": "SBP-101",
            "title": "Support Ticket Management System",
            "acceptance_criteria": [
                {"ac_key": "AC-01", "text": "POST /api/tickets creates ticket"},
                {"ac_key": "AC-02", "text": "Validation returns 400"},
                {"ac_key": "AC-03", "text": "GET /api/tickets/{id} returns ticket"},
                {"ac_key": "AC-04", "text": "PUT /api/tickets/{id} updates ticket"},
                {"ac_key": "AC-05", "text": "DELETE /api/tickets/{id} deletes ticket"},
                {"ac_key": "AC-06", "text": "Filter tickets by status"},
                {"ac_key": "AC-07", "text": "Pagination of tickets"},
                {"ac_key": "AC-08", "text": "Duplicate ticket rejection"},
            ]
        },
        "target_host": "http://localhost:5001",
        "collection_name": "Tickets API",
        "summary_recommendation": "API Conforms to Specifications",
        "decision_status": "Ready for Approval",
        "decision_summary": "Initial summary placeholder",
        "real_code_coverage": {
            "line_coverage_pct": 84.5,
            "branch_coverage_pct": 75.0,
            "num_statements": 120,
            "num_missing": 18,
            "is_mock": False,
        },
        "unit_tests": {
            "total": 9,
            "passed": 8,
            "failed": 1,
            "pass_rate_pct": 88.9,
            "test_cases": [
                {"test_key": f"TC-0{i}", "title": f"Scenario {i}", "status": "PASSED", "acceptance_criteria_ids": [f"AC-0{i}"]}
                for i in range(1, 9)
            ] + [
                {
                    "test_key": "TC-09",
                    "title": "Verify ticket update on non-existent resource",
                    "status": "FAILED",
                    "acceptance_criteria_ids": ["AC-04"],
                    "failure_reason": "Expected HTTP 404, got HTTP 500",
                    "error": "AssertionError: 500 != 404",
                    "execution_log": "AssertionError: Status code mismatch: expected 404 but got 500",
                }
            ],
            "failed_test_cases": [
                {
                    "test_key": "TC-09",
                    "title": "Verify ticket update on non-existent resource",
                    "status": "FAILED",
                    "acceptance_criteria_ids": ["AC-04"],
                    "failure_reason": "Expected HTTP 404, got HTTP 500",
                    "error": "AssertionError: 500 != 404",
                    "execution_log": "AssertionError: Status code mismatch: expected 404 but got 500",
                }
            ]
        },
        "results": [
            {
                "test_key": f"TC-API-0{i}",
                "endpoint": f"/api/tickets/{i}",
                "method": "GET",
                "passed": True,
                "status_code": 200,
                "duration_ms": 45,
                "ac_keys": [f"AC-0{i}"],
            }
            for i in range(1, 9)
        ],
        "total_endpoints": 8,
        "passed_endpoints": 8,
        "human_approval_status": "PENDING",
        "approver_name": "Release Lead",
        "sha256_seal": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "execution_trace": {
            "stages": [
                {"stage_order": 1, "stage_name": "requirement_analysis", "status": "PASS", "duration_ms": 1100, "tool_calls": ["requirement_analyzer"]},
                {"stage_order": 2, "stage_name": "unit_test_execution", "status": "FAIL", "duration_ms": 2500, "tool_calls": ["pytest"]},
                {"stage_order": 3, "stage_name": "api_verification", "status": "PASS", "duration_ms": 1400, "tool_calls": ["HttpRunner"]},
            ]
        }
    }


def test_docx_document_consistency(tmp_path, evidence_data_with_failed_unit_test):
    out_dir = str(tmp_path)
    docx_path = generate_docx_evidence(evidence_data_with_failed_unit_test, out_dir=out_dir)
    assert os.path.isfile(docx_path)

    doc = docx.Document(docx_path)
    all_text = "\n".join([p.text for p in doc.paragraphs])
    for t in doc.tables:
        for r in t.rows:
            all_text += "\n" + " | ".join([c.text for c in r.cells])

    # Fix 9 & Fix 22: Executive Recommendation reflects failed unit test and does NOT falsely claim "All tests passed"
    assert "API CONFORMS (UNIT TESTS REQUIRE ATTENTION)" in all_text
    assert "8/9" in all_text or "88.9%" in all_text
    assert "1 test(s) require review" in all_text
    assert "All 9 generated unit tests passed" not in all_text

    # Fix 10: Failed User-Story Test Analysis table is rendered
    assert "Failed User-Story Test Analysis" in all_text
    assert "TC-09" in all_text
    assert "Expected HTTP 404, got HTTP 500" in all_text or "AssertionError" in all_text

    # Fix 11: 8 ACs vs 9 tests explanation note is included
    assert "Investigation Note (Prompt Section 11):" in all_text
    assert "8 Acceptance Criteria vs 9 Generated Test Cases" in all_text

    # Fix 12: Zero implementation gaps separates API gaps from unit test failures
    assert "API Implementation Gaps: 0 based on executed API scenarios" in all_text
    assert "User Story Unit Test Failures: 1 test(s) failed or require review" in all_text

    # Fix 13: Final assessment basis
    assert "PARTIAL — Unit Test Failed" in all_text or "SATISFIED" in all_text

    # Fix 14 & 15: Coverage quality gate & Coverage scope
    assert "Coverage Quality Gate (Prompt Section 14):" in all_text
    assert "Coverage Scope (Prompt Section 15):" in all_text

    # Fix 16: Human Review Status
    assert "Human Review & Enterprise Signoff Status (Prompt Section 16)" in all_text
    assert "PENDING" in all_text

    # Fix 18: Execution Trace & Lifecycle Audit
    assert "Agent Execution Trace & Lifecycle Audit (Prompt Section 18)" in all_text

    # Fix 20: Metric Provenance Table
    assert "Evidence Metric Provenance & Authoritative Sources (Prompt Section 20):" in all_text

    # Fix 21: Cryptographic Audit Seal & Artifact Hashes
    assert "Cryptographic Audit Seal & Artifact Hashes (Prompt Section 21)" in all_text


def test_html_document_consistency(tmp_path, evidence_data_with_failed_unit_test):
    out_dir = str(tmp_path)
    html_path = render_autonomous_evidence_html(evidence_data_with_failed_unit_test, out_dir=out_dir)
    assert os.path.isfile(html_path)

    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # Fix 9 & Fix 22: Executive Recommendation in HTML
    assert "API CONFORMS (UNIT TESTS REQUIRE ATTENTION)" in html_content
    assert "1 test(s) require review" in html_content
    assert "All 9 generated unit tests passed" not in html_content

    # Fix 10: Failed test analysis in HTML
    assert "Failed User-Story Test Analysis" in html_content
    assert "TC-09" in html_content

    # Fix 11: 8 ACs vs 9 tests note in HTML
    assert "8 Acceptance Criteria vs 9 Generated Tests" in html_content

    # Fix 12: Zero implementation gaps in HTML
    assert "API Implementation Gaps: 0 based on executed API scenarios" in html_content
    assert "User Story Unit Test Failures: 1 test(s) failed or require review" in html_content

    # Fix 14 & 15: Coverage Quality Gate & Scope in HTML
    assert "Coverage Quality Gate (Prompt Section 14)" in html_content
    assert "Coverage Scope (Prompt Section 15)" in html_content

    # Fix 16: Human Review & Enterprise Signoff in HTML
    assert "Human Review &amp; Enterprise Signoff Status (Prompt Section 16)" in html_content

    # Fix 18: Execution Trace & Lifecycle Audit in HTML
    assert "Agent Execution Trace &amp; Lifecycle Audit (Prompt Section 18)" in html_content

    # Fix 20: Metric Provenance in HTML
    assert "Evidence Metric Provenance &amp; Authoritative Sources (Prompt Section 20)" in html_content

    # Fix 21: Cryptographic Audit Seal & Artifact Hashes in HTML
    assert "Cryptographic Audit Seal &amp; Artifact Hashes (Prompt Section 21)" in html_content
