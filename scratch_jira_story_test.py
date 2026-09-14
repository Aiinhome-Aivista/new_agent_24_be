import json
from app.agents.api_executor.autonomous_agent import AutonomousApiVerifierAgent
from app.tools.api_runner.collection_parser import parse_postman_collection

agent = AutonomousApiVerifierAgent()
with open('../ticket-management.postman_collection.json', 'r', encoding='utf-8') as f:
    col = json.load(f)

baseline = parse_postman_collection(col)
story = {
    'title': 'Create Support Ticket and Retrieve Ticket by ID (Public API)',
    'description': '''As an application user, I want to submit a support ticket with structured details and retrieve existing tickets by ID, so that I can report issues, track technical requests, and verify ticket status without requiring authentication.'''
}

# The 8 ACs from Jira
acs = [
    {'ac_key': 'AC-01', 'text': 'AC-01 — Successful Support Ticket Creation (Happy Path)\nGiven a client sends a valid ticket request\nWhen the client sends a POST request to /api/tickets with valid title, description, category, and priority\nThen the system shall create the ticket\nAnd return HTTP status 201 Created\nAnd return the created ticket object containing id, ticket_key, title, description, category, priority, status ("OPEN"), and created_at.'},
    {'ac_key': 'AC-02', 'text': 'AC-02 — Missing Required Fields\nGiven the ticket creation API requires title, description, and category\nWhen any of these required fields is omitted or empty\nThen the system shall reject the request\nAnd return HTTP status 400 Bad Request\nAnd return an error message indicating that title, description, and category are required.'},
    {'ac_key': 'AC-03', 'text': 'AC-03 — Category Validation\nGiven allowed ticket categories are strictly technical, billing, account, and feature\nWhen the client submits an unrecognized category (e.g., invalid-category or sales)\nThen the system shall reject the request\nAnd return HTTP status 400 Bad Request\nAnd return an error message indicating allowed category values.'},
    {'ac_key': 'AC-04', 'text': 'AC-04 — Priority Validation\nGiven allowed priority levels are low, medium, high, and urgent\nWhen the client submits an invalid priority string (e.g., extreme or critical)\nThen the system shall reject the request\nAnd return HTTP status 400 Bad Request\nAnd return an error message indicating allowed priority values.'},
    {'ac_key': 'AC-05', 'text': 'AC-05 — Title Length Boundary Validation\nGiven ticket title length constraint is between 5 and 100 characters (inclusive)\nWhen a user submits a title with fewer than 5 characters (e.g., "Bug") or greater than 100 characters\nThen the system shall reject the request\nAnd return HTTP status 400 Bad Request\nAnd titles of exactly 5 characters and exactly 100 characters must be accepted.'},
    {'ac_key': 'AC-06', 'text': 'AC-06 — Non-JSON Request Rejection\nGiven /api/tickets expects a JSON request body\nWhen the client sends a non-JSON payload or invalid Content-Type\nThen the system shall reject the request\nAnd return HTTP status 400 Bad Request.'},
    {'ac_key': 'AC-07', 'text': 'AC-07 — Retrieve Existing Ticket by ID\nGiven a ticket exists with a known numeric ID (e.g., 101)\nWhen a client sends a GET request to /api/tickets/101\nThen the system shall return HTTP status 200 OK\nAnd return the full ticket details matching ID 101.'},
    {'ac_key': 'AC-08', 'text': 'AC-08 — Retrieve Non-Existent Ticket\nGiven a ticket ID does not exist in the database (e.g., 9999)\nWhen a client sends a GET request to /api/tickets/9999\nThen the system shall return HTTP status 404 Not Found\nAnd return an error message "Ticket not found".'},
]

# Generate synthesized endpoints
endpoints = agent.synthesize_ac_scenarios(baseline, story, acs)

from app.tools.api_runner.runner import HttpRunner
runner = HttpRunner(timeout=15)
run_result = runner.run(endpoints=endpoints, base_url='http://localhost:5001')

story_expectations = agent._extract_story_expectations(story, acs)

print("====================================================")
print(f"Total Test Cases Executed: {len(run_result.results)}")
print(f"Passed Assertions: {run_result.passed}")
print(f"Failed Assertions: {run_result.failed}")
print("====================================================")

all_devs = []
for idx, r in enumerate(run_result.results):
    ep = endpoints[idx] if idx < len(endpoints) else {}
    devs = agent._validate_response_against_requirements(ep, r, story_expectations)
    all_devs.extend(devs)
    test_key = ep.get('test_key') or r.get('endpoint')
    status = r.get('status_code')
    passed = r.get('passed')
    for d in devs:
        print(f"   [DEVIATION] {d}")
    print(f"-> {test_key}: Status {status} | Passed: {passed} | Deviations: {len(devs)}")

print("====================================================")
print(f"OVERALL RECOMMENDATION: {'API CONFORMS (PASS)' if len(all_devs) == 0 else 'API DEVIATES'}")
print(f"TOTAL ANOMALIES FLAGGED: {len(all_devs)}")
print("====================================================")
