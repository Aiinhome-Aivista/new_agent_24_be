import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')
import json
from app.agents.api_executor.autonomous_agent import AutonomousApiVerifierAgent

data = json.load(open('c:/Users/ADMIN/Desktop/Agent-24/ticket-management.postman_collection.json'))
agent = AutonomousApiVerifierAgent()
res = agent.execute_autonomous_verification('http://localhost:5001', data)
print(f"Summary: {res['summary_recommendation']}")
print(f"Summary Recommendation: {res['summary_recommendation']}")
print(f"Decision Status: {res['decision_status']}")
print(f"Endpoints Executed: {res['total_endpoints_executed']}")
print(f"Total Deviations: {len(res['deviations'])}")
for r in res['results']:
    print(f"  - {r['method']} {r['endpoint']} -> HTTP {r['status_code']} (Expected: {r['expected_status_code']}, Passed: {r['passed']})")
