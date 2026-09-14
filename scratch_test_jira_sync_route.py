import requests

BASE_API = "http://localhost:5000/api/v1"

s = requests.Session()
r_login = s.post(f"{BASE_API}/login", json={"email": "developer@tdd.local", "password": "Passw0rd!"})
token = r_login.json().get("data", {}).get("access_token")
print(f"Login success: {bool(token)}")

headers = {"Authorization": f"Bearer {token}"}

# First trigger autonomous run to get live evidence
r_run = s.post(f"{BASE_API}/api-executor/autonomous-run", headers=headers, json={"base_url": "http://localhost:5001"})
ev_data = r_run.json().get("data", {})
ev_key = ev_data.get("evidence_key")
print(f"Generated Evidence: {ev_key} (Endpoints: {ev_data.get('total_endpoints')})")

# Now sync evidence to Jira Story SCRUM-40
sync_payload = {
    "issue_key": "SCRUM-40",
    "evidence_key": ev_key,
    "evidence_data": ev_data,
    "comment_note": "Human-approved test evidence package from Autonomous Verification Agent.",
    "approver_name": "Lead QA Reviewer",
}

r_sync = s.post(f"{BASE_API}/jira/sync-evidence", headers=headers, json=sync_payload)
print(f"Jira sync status code: {r_sync.status_code}")
print("Response:", r_sync.json())
