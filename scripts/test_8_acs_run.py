import sys
import json
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.agents.api_executor.autonomous_agent import AutonomousApiVerifierAgent
from app.tools.document_generator.docx_generator import generate_docx_evidence

with open('c:/Users/ADMIN/Desktop/Agent-24/ticket-management.postman_collection.json', 'r', encoding='utf-8') as f:
    col_data = json.load(f)

agent = AutonomousApiVerifierAgent()
evidence = agent.execute_autonomous_verification(
    base_url='http://localhost:5001',
    collection_data=col_data,
    story_uuid='2188b0fe-8673-4d57-a1f7-ad79bf38d0a4',
    collection_name='Ticket Management API',
    is_mock=False
)

print(f"Total endpoints: {evidence['total_endpoints']}")
print(f"Passed endpoints: {evidence['passed_endpoints']}")
print(f"Failed endpoints: {evidence['failed_endpoints']}")
print(f"Total deviations: {evidence['total_deviations']}")
print(f"Summary recommendation: {evidence['summary_recommendation']}")

for idx, r in enumerate(evidence['results']):
    print(f"Case #{idx+1}: [{r['method']}] {r['endpoint']} -> HTTP {r['status_code']} (Expected: {r['expected_status_code']}, Passed: {r['passed']})")

docx_path = generate_docx_evidence(evidence, out_dir='c:/Users/ADMIN/Desktop/Agent-24/new_agent_24_be/evidence_output')
print(f"Generated DOCX at: {docx_path}")
print(f"File exists: {os.path.exists(docx_path)}, size: {os.path.getsize(docx_path)} bytes")
