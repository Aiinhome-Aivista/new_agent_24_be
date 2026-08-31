import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')
import json
from app.agents.test_generator.agent import TestGeneratorAgent

story = {
    "id": 14,
    "external_key": "SBP-101",
    "title": "User Management | Change Password & Account Security Enhancement",
    "description": (
        "Currently, the Spring Boot CRUD POC application supports user registration, "
        "JWT-based login, and CRUD operations on user records, but does not provide a "
        "dedicated, secure flow for an authenticated user to change their own password. "
        "This story adds a \"Change Password\" capability to the existing Auth module, "
        "ensuring old-password verification, new-password strength validation, and "
        "invalidation of previously issued JWT tokens after a successful change."
    ),
}

acs = [
    "Given I am a logged-in user with a valid JWT, When I call `POST /api/auth/change-password` with my current password and a new password, Then the system verifies the current password against the stored hash before proceeding.",
    "Given my current password does not match the stored hash, When I submit a change-password request, Then the system must reject the request with a `400 Bad Request` and an \"Incorrect current password\" message.",
    "Given I submit a new password that does not meet the strength policy (min 8 chars, 1 number, 1 special character), When the request is validated, Then the system must reject the request with a `400 Bad Request` and list the failed rule(s).",
    "Given my current password is correct and the new password passes validation, When the change-password request is processed, Then the system must update the stored password hash and return a `200 OK` response.",
    "Given my password has just been changed successfully, When any previously issued JWT for my account is used again, Then the system must reject it as invalid, forcing re-login with the new password.",
    "Given I am not authenticated (no/invalid JWT), When I call the change-password endpoint, Then the system must return a `401 Unauthorized` response and must not process the request.",
    "Given the password change succeeds, When the response is returned to the client, Then the response body must never include the password or password hash in plaintext or otherwise."
]

contracts = [
    {"method": "POST", "path": "{{base_url}}/api/auth/register", "service": "AuthService"},
    {"method": "POST", "path": "{{base_url}}/api/auth/login", "service": "AuthService"},
    {"method": "GET", "path": "{{base_url}}/api/users", "service": "UserService"},
    {"method": "GET", "path": "{{base_url}}/api/users/{{user_id}}", "service": "UserService"},
    {"method": "POST", "path": "{{base_url}}/api/users", "service": "UserService"},
    {"method": "PUT", "path": "{{base_url}}/api/users/{{user_id}}", "service": "UserService"},
    {"method": "DELETE", "path": "{{base_url}}/api/users/{{user_id}}", "service": "UserService"}
]

initial_state = {
    "story": story,
    "acceptance_criteria": acs,
    "api_contracts": contracts,
    "project": {"id": 1, "target_language": "java", "target_framework": "junit5"},
    "project_knowledge": "Spring Boot CRUD POC with JWT authentication filter and BCrypt password encoder.",
    "codebase_context": ""
}

from app.extensions.db import execute

wf_id = "wf-val-sbp101"
execute("""
    INSERT INTO workflow_runs (workflow_id, project_id, story_id, current_stage, status, state_json)
    VALUES (%s, 1, 14, 'TEST_GENERATION', 'RUNNING', '{}')
    ON DUPLICATE KEY UPDATE current_stage='TEST_GENERATION', status='RUNNING'
""", (wf_id,))

agent = TestGeneratorAgent()
final_state = agent.run(wf_id, initial_state)

tests = final_state.get("generated_tests", [])
print(f"=== TOTAL TESTS GENERATED: {len(tests)} ===")
for t in tests:
    print(f"[{t.get('test_key')}] [{t.get('test_type')}] [{t.get('scenario_type')}]")
    print(f"Title: {t.get('title')}")
    print(f"Story Reference: {t.get('story_reference')}")
    print(f"AC IDs: {t.get('acceptance_criteria_ids')}")
    print(f"Priority: {t.get('priority')}")
    print(f"Preconditions: {t.get('preconditions')}")
    print(f"Test Data: {t.get('test_data')}")
    print(f"Test Steps: {t.get('test_steps')}")
    print(f"Expected Result: {t.get('expected_result')}")
    print(f"Request Spec: {t.get('request_spec')}")
    print(f"Expected Response Spec: {t.get('expected_response_spec')}")
    print(f"Grounding Metadata: {t.get('grounding_metadata')}")
    print(f"Requires Review: {t.get('requires_review')}")
    print(f"Assumption Details: {t.get('assumption_details')}")
    print(f"Responsible Functions: {t.get('responsible_functions')}")
    print("-" * 60)
