import requests

s = requests.Session()
r_login = s.post('http://localhost:5000/api/v1/login', json={'email': 'developer@tdd.local', 'password': 'Passw0rd!'})
token = r_login.json()['data']['access_token']
headers = {'Authorization': f'Bearer {token}'}

# Get sample collections
cols = s.get('http://localhost:5000/api/v1/api-executor/sample-collections', headers=headers).json().get('data', {}).get('collections', [])
ticket_col = next((c for c in cols if 'ticket' in c['name'].lower()), cols[0])

# Get stories
stories = s.get('http://localhost:5000/api/v1/stories', headers=headers).json().get('data', {}).get('stories', [])
ticket_story = next((st for st in stories if 'ticket' in st.get('title', '').lower()), None)

print(f"Testing with Collection: {ticket_col['name']}, Story: {ticket_story.get('title') if ticket_story else 'None'}")

r_run = s.post('http://localhost:5000/api/v1/api-executor/autonomous-run', headers=headers, json={
    'base_url': 'http://localhost:5001',
    'collection_json': ticket_col['collection'],
    'collection_name': ticket_col['name'],
    'story_uuid': ticket_story['uuid'] if ticket_story else None
})
ev_data = r_run.json().get('data', {})

print("==================================================")
print(f"Total Endpoints: {ev_data.get('total_endpoints')}")
print(f"Passed Endpoints: {ev_data.get('passed_endpoints')}")
print(f"Total Deviations: {ev_data.get('total_deviations')}")
print(f"Recommendation: {ev_data.get('summary_recommendation')}")
print("==================================================")

for r in ev_data.get('results', []):
    test_name = r.get('test_key') or r.get('endpoint')
    status = r.get('status_code')
    passed = r.get('passed')
    dev_count = len(r.get('deviations') or [])
    print(f"-> {test_name}: Status {status} | Passed: {passed} | Deviations: {dev_count}")
