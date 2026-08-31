"""Unit tests for Test Case Generation Upgrades, Deduplication, AC Coverage, and Source Grounding."""
import pytest
from app.agents.test_generator.test_validator import (
    TestCaseDeduplicator,
    TestCaseValidator,
    AcceptanceCriteriaCoverageValidator,
    GenerationSummaryCalculator,
    ContractGapDetector
)
from app.agents.test_generator.agent import TestGeneratorAgent


def test_deduplicator_removes_true_duplicates_but_preserves_distinct_conditions():
    raw_tests = [
        {
            "title": "Reject incorrect current password",
            "scenario_type": "negative",
            "acceptance_criteria_ids": ["AC-02"],
            "story_reference": "AC-02: Incorrect current password",
            "request_spec": {"method": "POST", "endpoint": "/api/auth/change-password"}
        },
        {
            "title": "Verify rejection of incorrect current password with 400",
            "scenario_type": "negative",
            "acceptance_criteria_ids": ["AC-02"],
            "story_reference": "AC-02: Incorrect current password",
            "request_spec": {"method": "POST", "endpoint": "/api/auth/change-password"}
        },
        {
            "title": "Reject new password shorter than 8 characters",
            "scenario_type": "boundary",
            "acceptance_criteria_ids": ["AC-03"],
            "story_reference": "AC-03: Length below 8 characters",
            "request_spec": {"method": "POST", "endpoint": "/api/auth/change-password"}
        },
        {
            "title": "Reject new password missing a number",
            "scenario_type": "validation",
            "acceptance_criteria_ids": ["AC-03"],
            "story_reference": "AC-03: Missing number",
            "request_spec": {"method": "POST", "endpoint": "/api/auth/change-password"}
        },
        {
            "title": "Reject new password missing a special character",
            "scenario_type": "validation",
            "acceptance_criteria_ids": ["AC-03"],
            "story_reference": "AC-03: Missing special char",
            "request_spec": {"method": "POST", "endpoint": "/api/auth/change-password"}
        },
        {
            "title": "Successfully change password with valid criteria",
            "scenario_type": "positive",
            "acceptance_criteria_ids": ["AC-01", "AC-04"],
            "story_reference": "AC-01: Valid password change",
            "request_spec": {"method": "POST", "endpoint": "/api/auth/change-password"}
        }
    ]

    deduped = TestCaseDeduplicator.deduplicate(raw_tests, story_key="SBP-101")
    # Duplicate AC-02 should be merged, but separate AC-03 scenarios should be preserved
    assert len(deduped) == 5
    assert deduped[0]["test_key"] == "TC-SBP101-001"
    assert deduped[4]["test_key"] == "TC-SBP101-005"


def test_acceptance_criteria_coverage_validator():
    acs = [
        "Given valid JWT, call POST /api/auth/change-password",
        "Given incorrect current password, return 400 Bad Request with 'Incorrect current password'",
        "Given weak password, return 400 Bad Request and list failed rules",
        "Given valid inputs, update hash and return 200 OK",
        "Given password changed, invalidate previously issued JWTs",
        "Given unauthenticated request, return 401 Unauthorized",
        "Given successful change, do not expose password or hash in response"
    ]

    test_cases = [
        {"test_key": "TC-SBP101-001", "acceptance_criteria_ids": ["AC-01", "AC-04"], "story_reference": "AC-01"},
        {"test_key": "TC-SBP101-002", "acceptance_criteria_ids": ["AC-02"], "story_reference": "AC-02"},
        {"test_key": "TC-SBP101-003", "acceptance_criteria_ids": ["AC-03"], "story_reference": "AC-03"},
        {"test_key": "TC-SBP101-004", "acceptance_criteria_ids": ["AC-05"], "story_reference": "AC-05"},
        {"test_key": "TC-SBP101-005", "acceptance_criteria_ids": ["AC-06"], "story_reference": "AC-06"},
        {"test_key": "TC-SBP101-006", "acceptance_criteria_ids": ["AC-07"], "story_reference": "AC-07"},
    ]

    report = AcceptanceCriteriaCoverageValidator.validate_coverage(test_cases, acs)
    assert report["coverage_complete"] is True
    assert report["covered_acceptance_criteria"] == 7
    assert report["total_acceptance_criteria"] == 7
    assert report["coverage_pct"] == 100.0
    assert len(report["missing_acceptance_criteria"]) == 0
    assert len(report["coverage_matrix"]) == 7


def test_generation_summary_calculator():
    test_cases = [
        {
            "test_key": "TC-001",
            "grounding_metadata": {"overall_grounding": "CONFIRMED"},
            "requires_review": False
        },
        {
            "test_key": "TC-002",
            "grounding_metadata": {"overall_grounding": "PARTIALLY_CONFIRMED"},
            "requires_review": False
        },
        {
            "test_key": "TC-003",
            "grounding_metadata": {"overall_grounding": "NEEDS_REVIEW"},
            "requires_review": True
        }
    ]
    coverage_report = {
        "total_acceptance_criteria": 3,
        "covered_acceptance_criteria": 3,
        "coverage_pct": 100.0,
        "coverage_complete": True,
        "missing_acceptance_criteria": []
    }
    gaps = [{"method": "POST", "endpoint": "/api/auth/change-password"}]

    summary = GenerationSummaryCalculator.calculate(
        total_candidates=5,
        final_test_cases=test_cases,
        coverage_report=coverage_report,
        contract_gaps=gaps
    )

    assert summary["total_candidates"] == 5
    assert summary["duplicates_removed"] == 2
    assert summary["final_unique_test_cases"] == 3
    assert summary["grounding_confirmed"] == 1
    assert summary["grounding_partially_confirmed"] == 1
    assert summary["needs_review"] == 1
    assert summary["contract_gaps"] == 1


def test_validator_checks_source_grounding_and_assumptions():
    valid_tc = {
        "test_key": "TC-SBP101-001",
        "title": "Successfully change password with valid criteria",
        "scenario_type": "positive",
        "test_type": "API",
        "story_reference": "AC-01: Valid password change",
        "grounding_metadata": {
            "endpoint": {"source": "STORY", "reference": "AC-01"},
            "status_code": {"source": "ACCEPTANCE_CRITERIA", "reference": "AC-04"},
            "response_body": {"source": "ACCEPTANCE_CRITERIA"}
        },
        "expected_response_spec": {
            "status_code": 200,
            "status_source": "ACCEPTANCE_CRITERIA",
            "response_body_source": "ACCEPTANCE_CRITERIA"
        }
    }
    is_valid, errors = TestCaseValidator.validate_test_case(valid_tc, {}, [], has_codebase=False)
    assert is_valid
    assert len(errors) == 0
    assert valid_tc["grounding_metadata"]["overall_grounding"] == "CONFIRMED"
    assert valid_tc["responsible_functions"] is None
    assert valid_tc["responsible_functions_source"] == "UNKNOWN"

    # Inferred status should enforce requires_review = True and NEEDS_REVIEW
    assumed_tc = {
        "test_key": "TC-SBP101-002",
        "title": "Inferred database failure error",
        "scenario_type": "error",
        "test_type": "API",
        "story_reference": "AC-07: Error handling",
        "expected_response_spec": {
            "status_code": 500,
            "status_source": "AI_ASSUMPTION"
        }
    }
    is_valid, errors = TestCaseValidator.validate_test_case(assumed_tc, {}, [], has_codebase=False)
    assert is_valid
    assert assumed_tc["requires_review"] is True
    assert "inferred by AI" in assumed_tc["assumption_details"]
    assert assumed_tc["grounding_metadata"]["overall_grounding"] == "NEEDS_REVIEW"


def test_contract_gap_detector_identifies_missing_endpoints():
    story = {
        "title": "Change Password",
        "description": "User calls POST /api/auth/change-password with current and new password."
    }
    acs = ["AC-01: Given valid JWT, call POST /api/auth/change-password"]
    contracts = [
        {"method": "POST", "path": "/api/auth/login", "service": "AuthService"},
        {"method": "POST", "path": "/api/auth/register", "service": "AuthService"},
        {"method": "GET", "path": "/api/users", "service": "UserService"}
    ]

    gaps = ContractGapDetector.detect_gaps(story, acs, contracts)
    assert len(gaps) == 1
    assert gaps[0]["endpoint"] == "/api/auth/change-password"
    assert gaps[0]["method"] == "POST"
    assert gaps[0]["status"] == "NOT_FOUND_IN_UPLOADED_COLLECTION"


def test_derive_systematic_scenarios_for_sbp101():
    agent = TestGeneratorAgent()
    story = {
        "title": "User Management | Change Password & Account Security Enhancement",
        "description": "Change password flow for authenticated user"
    }
    acs = [
        "AC-01: Verify current password against stored hash",
        "AC-02: Incorrect current password returns 400 Bad Request and 'Incorrect current password'",
        "AC-03: Password strength validation (min 8 chars, 1 number, 1 special character)",
        "AC-04: Update stored password hash and return 200 OK",
        "AC-05: Invalidate previously issued JWTs",
        "AC-06: Return 401 Unauthorized for missing/invalid JWT",
        "AC-07: Never expose password or hash in response body"
    ]
    derived = agent._derive_systematic_scenarios(story, acs, [], "java", "junit5", "SBP101", has_codebase=False)
    assert len(derived) >= 10

    # Verify AC-02 has explicit error message
    ac02_tc = next(t for t in derived if "AC-02" in t["acceptance_criteria_ids"])
    assert ac02_tc["expected_response_spec"]["response_body"] == {"message": "Incorrect current password"}
    assert ac02_tc["expected_response_spec"]["response_body_source"] == "ACCEPTANCE_CRITERIA"
    assert ac02_tc["grounding_metadata"]["overall_grounding"] == "CONFIRMED"

    # Verify AC-05 has AI_ASSUMPTION and requires_review
    ac05_tc = next(t for t in derived if "AC-05" in t["acceptance_criteria_ids"])
    assert ac05_tc["expected_response_spec"]["status_source"] == "AI_ASSUMPTION"
    assert ac05_tc["requires_review"] is True

    # Verify AC-07 exists as a security test case
    ac07_tc = next(t for t in derived if "AC-07" in t["acceptance_criteria_ids"])
    assert ac07_tc["scenario_type"] == "security"

    # Verify AC-03 has compound scenarios
    ac03_tcs = [t for t in derived if "AC-03" in t["acceptance_criteria_ids"]]
    assert len(ac03_tcs) >= 5
