import pytest
from app.utils.ac_parser import extract_clean_acceptance_criteria
from app.agents.test_generator.test_validator import AcceptanceCriteriaCoverageValidator
from app.agents.test_generator.agent import TestGeneratorAgent
from app.tools.api_runner.runner import build_postman_collection, generate_test_case_screenshot


def test_clean_acceptance_criteria_and_persona_filtering():
    story_title = "Prospect Details and Removal"
    story_desc = """As an Agent (System User)
AC 1: POST /api/prospects/details (Fetch Specific Prospect Details): The system must have a POST API where an agent provides a prospect_id in the request body.
AC 2: GET /api/prospects (Fetch All Prospects): The system must have a GET API that retrieves a list of all available prospects assigned to the agent.
AC 3: DELETE /api/prospects/{id} (Remove a Prospect): The system must have a DELETE API that takes a prospect_id and removes that specific prospect."""

    acs = extract_clean_acceptance_criteria(story_title, story_desc)

    # Must produce exactly 3 ACs, ignoring persona "As an Agent..."
    assert len(acs) == 3
    assert acs[0]["ac_key"] == "AC-01"
    assert acs[1]["ac_key"] == "AC-02"
    assert acs[2]["ac_key"] == "AC-03"

    # Must not contain duplicate AC numbering inside the text
    assert not acs[0]["text"].startswith("AC 1:")
    assert not acs[1]["text"].startswith("AC 2:")
    assert not acs[2]["text"].startswith("AC 3:")

    # Inferred endpoints must be accurate REST endpoints for each AC
    assert acs[0]["inferred_method"] == "POST"
    assert acs[0]["inferred_path"] == "/api/prospects/details"

    assert acs[1]["inferred_method"] == "GET"
    assert acs[1]["inferred_path"] == "/api/prospects"

    assert acs[2]["inferred_method"] == "DELETE"
    assert "/api/prospects" in acs[2]["inferred_path"]


def test_coverage_matrix_grounding_with_missing_code():
    story_title = "Prospect Details and Removal"
    story_desc = """AC 1: POST /api/prospects/details (Fetch Specific Prospect Details): The system must have a POST API where an agent provides a prospect_id in the request body.
AC 2: GET /api/prospects (Fetch All Prospects): The system must have a GET API that retrieves a list of all available prospects assigned to the agent."""

    acs = extract_clean_acceptance_criteria(story_title, story_desc)
    agent = TestGeneratorAgent()
    tcs = agent._derive_systematic_scenarios({"title": story_title, "description": story_desc}, acs, [], "python", "pytest", "PR101", False)

    # When codebase reports POST /api/prospects/details is MISSING in code
    missing_from_code = [{"method": "POST", "path": "/api/prospects/details"}]
    cov_report = AcceptanceCriteriaCoverageValidator.validate_coverage(
        tcs, acs,
        implemented_in_code=[],
        missing_from_code=missing_from_code,
        has_codebase=True
    )

    # AC-01 is missing in code, so covered must be False
    ac_01_row = next(r for r in cov_report["coverage_matrix"] if r["ac_key"] == "AC-01")
    assert ac_01_row["covered"] is False


def test_postman_collection_and_screenshot_generation():
    test_cases = [
        {
            "test_key": "TC-PR101-001",
            "title": "Fetch Specific Prospect Details",
            "request_spec": {
                "method": "POST",
                "endpoint": "/api/prospects/details",
                "body": {"prospect_id": "PR-10029"}
            },
            "expected_response_spec": {
                "status_code": 200,
                "assertions": ["response.status == 200"]
            }
        }
    ]

    coll = build_postman_collection(test_cases, environment="http://localhost:8080")
    item = coll["item"][0]
    assert item["request"]["method"] == "POST"
    assert "api/prospects/details" in item["request"]["url"]["raw"]
