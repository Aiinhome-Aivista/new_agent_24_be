import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')
import json
from app.agents.test_generator.agent import TestGeneratorAgent
from app.agents.test_generator.test_validator import TestCaseValidator, AcceptanceCriteriaCoverageValidator

# Real-world User Story: pure business criteria, NO technical URLs, NO JSON schemas in story text!
pure_business_story = {
    "id": 99,
    "external_key": "TKT-200",
    "title": "Customer Support Ticket Management",
    "description": "Users can submit support tickets and query existing tickets.",
}

pure_business_acs = [
    {"ac_key": "AC-01", "text": "When user submits a ticket with valid title, description, and category, ticket is created successfully with status OPEN and returns 201."},
    {"ac_key": "AC-02", "text": "When user submits a ticket without a title, reject request with 400 Bad Request and error 'Title is required'."},
    {"ac_key": "AC-03", "text": "When user submits an invalid category, reject with 400 Bad Request and error 'Category must be one of: technical, billing, account, feature'."},
    {"ac_key": "AC-04", "text": "When user requests a ticket by ID that does not exist, return 404 Not Found with error 'Ticket not found'."},
]

# Postman Collection Contracts: Contains technical URLs, Headers, Sample Request Body, Sample Response
postman_contracts = [
    {
        "service": "TicketService",
        "method": "POST",
        "path": "/api/tickets",
        "headers": {"Content-Type": "application/json"},
        "sample_request": {
            "title": "Payment gateway timeout",
            "description": "Checkout fails on step 3 with 504 error",
            "category": "technical",
            "priority": "high"
        },
        "sample_response": {
            "id": 101,
            "ticket_key": "TKT-101",
            "status": "OPEN",
            "created_at": "2026-09-08T10:00:00Z"
        },
        "expected_status_code": 201
    },
    {
        "service": "TicketService",
        "method": "GET",
        "path": "/api/tickets/101",
        "headers": {"Accept": "application/json"},
        "sample_request": None,
        "sample_response": {
            "id": 101,
            "ticket_key": "TKT-101",
            "title": "Payment gateway timeout",
            "category": "technical",
            "status": "OPEN"
        },
        "expected_status_code": 200
    }
]

state = {
    "story": pure_business_story,
    "acceptance_criteria": pure_business_acs,
    "api_contracts": postman_contracts,
    "project": {"id": 1, "target_language": "python", "target_framework": "pytest"},
}

agent = TestGeneratorAgent()
derived_tests = agent._derive_systematic_scenarios(
    pure_business_story,
    pure_business_acs,
    postman_contracts,
    lang="python",
    framework="pytest",
    clean_story_key="TKT200",
    has_codebase=False
)

print(f"Generated {len(derived_tests)} test cases from Pure Business Story + Postman Contracts:")
for tc in derived_tests:
    req = tc.get("request_spec", {})
    res = tc.get("expected_response_spec", {})
    grounding = tc.get("grounding_metadata", {})
    print(f"\n[Test Key]: {tc.get('test_key')} | [ACs]: {tc.get('acceptance_criteria_ids')}")
    print(f"  Title: {tc.get('title')}")
    print(f"  Technical Endpoint: {req.get('method')} {req.get('endpoint')} (source: {grounding.get('endpoint', {}).get('source')})")
    print(f"  Headers: {req.get('headers')}")
    print(f"  Payload: {req.get('body')} (data source: {tc.get('test_data_source')})")
    print(f"  Response Spec: HTTP {res.get('status_code')} | Body: {res.get('response_body')} (source: {res.get('response_body_source')})")
    print(f"  Overall Grounding: {grounding.get('overall_grounding')}")

# Validate coverage
cov = AcceptanceCriteriaCoverageValidator.validate_coverage(derived_tests, pure_business_acs)
print(f"\nAC Coverage: {cov['covered_acceptance_criteria']}/{cov['total_acceptance_criteria']} ({cov['coverage_pct']}%)")
assert cov["coverage_pct"] == 100.0, "Coverage must be 100%"
print("ALL TESTS PASSED WITH 100% POSTMAN GROUNDING!")
