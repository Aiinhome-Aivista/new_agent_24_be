import json
from app.agents.api_executor.autonomous_agent import AutonomousApiVerifierAgent
from app.repositories.project_repo import get_story, story_acceptance_criteria
from app.tools.api_runner.collection_parser import parse_postman_collection

agent = AutonomousApiVerifierAgent()
with open('../ticket-management.postman_collection.json', 'r', encoding='utf-8') as f:
    col = json.load(f)

baseline = parse_postman_collection(col)
story = get_story("2188b0fe-8673-4d57-a1f7-ad79bf38d0a4")
acs = story_acceptance_criteria(story["id"])

print("Testing AI synthesis...")
ai_scenarios = agent._synthesize_ac_scenarios_ai(baseline, story, acs)
print("AI scenarios returned:", len(ai_scenarios) if ai_scenarios else None)
if ai_scenarios:
    for s in ai_scenarios:
        print(f"  [{s.get('ac_key')}] method: {s.get('method')} | path: {s.get('path')} | body: {s.get('body')} | status: {s.get('expected_status_code')}")

print("\nTesting Full synthesize_ac_scenarios...")
endpoints = agent.synthesize_ac_scenarios(baseline, story, acs)
print("Total endpoints returned:", len(endpoints))
for idx, ep in enumerate(endpoints):
    print(f"  {idx+1}. [{ep.get('ac_key')}] {ep.get('test_key')} -> body: {ep.get('body')}")
