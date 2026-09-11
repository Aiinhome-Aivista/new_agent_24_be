import json
import os
import re
from app.llm.model_router.router import get_router
from app.llm.client.gemini_client import _clean_json_text

def test_llm_synthesis():
    router = get_router()
    
    baseline_endpoints = [
        {
            "method": "POST",
            "path": "/api/tickets",
            "headers": {"Content-Type": "application/json"},
            "body": {
                "title": "Payment gateway timeout on checkout",
                "description": "Customers reporting 504 errors",
                "category": "technical",
                "priority": "high"
            }
        },
        {
            "method": "GET",
            "path": "/api/tickets/101",
            "headers": {},
            "body": None
        }
    ]
    
    with open("../Ticket-Management-Story.md", "r", encoding="utf-8") as f:
        content = f.read()
        
    acs = []
    matches = re.finditer(r'###\s*(AC-\d+)\s*[—\-:]\s*([^\n]+)\n(.*?)(?=\n###|\n---\s*$|\Z)', content, re.DOTALL)
    for m in matches:
        acs.append({"ac_key": m.group(1).strip(), "text": f"{m.group(2).strip()}\n{m.group(3).strip()}"})
        
    system_prompt = """You are an Autonomous API Test Generation Agent.
Given a baseline Postman collection (endpoints, methods, payload structures) and a list of Acceptance Criteria (ACs),
you must synthesize an executable test scenario for EACH Acceptance Criterion.

RULES:
1. Generate exactly 1 test scenario for each Acceptance Criterion.
2. For happy paths / positive ACs: use the baseline endpoint and a fully valid request body.
3. For negative/validation ACs: mutate, omit, or modify the specific parameter/field/path described in the AC (e.g. missing required fields, invalid enum/value, length boundary violations, non-JSON body, non-existent ID in path) while keeping the rest compliant with the API contract.
4. Output ONLY a valid JSON array of objects with the exact schema:
[
  {
    "test_key": "1. AC-01 — Scenario Title",
    "ac_key": "AC-01",
    "method": "POST",
    "path": "/api/path",
    "headers": {"Content-Type": "application/json"},
    "body": <json object or string or null>,
    "expected_status_code": 201,
    "expected_error_contains": "<substring if error expected, else null>",
    "assertions": ["Status is 201", "Assertion 2"]
  }
]
"""
    user_prompt = f"""
Baseline Postman Endpoints:
{json.dumps(baseline_endpoints, indent=2)}

Acceptance Criteria to Test:
{json.dumps(acs, indent=2)}

Generate all {len(acs)} test scenarios in valid JSON format:
"""
    
    print("Calling Gemini via ModelRouter...")
    llm_res = router.generate_structured("test_generation", user_prompt, system=system_prompt)
    raw_text = llm_res.text if hasattr(llm_res, "text") else str(llm_res)
    cleaned = _clean_json_text(raw_text)
    parsed = json.loads(cleaned)
    if isinstance(parsed, dict) and "test_scenarios" in parsed:
        parsed = parsed["test_scenarios"]
    elif isinstance(parsed, dict) and "test_cases" in parsed:
        parsed = parsed["test_cases"]
    elif isinstance(parsed, dict) and "scenarios" in parsed:
        parsed = parsed["scenarios"]
        
    print(f"Successfully generated {len(parsed)} scenarios via Gemini:")
    for idx, sc in enumerate(parsed):
        print(f"  {idx+1}. [{sc.get('method')}] {sc.get('test_key')} -> Expected HTTP {sc.get('expected_status_code')}")
        print(f"     Path: {sc.get('path')}")
        print(f"     Body: {sc.get('body')}")
        print(f"     Expected Error Contains: {sc.get('expected_error_contains')}")

if __name__ == "__main__":
    test_llm_synthesis()
