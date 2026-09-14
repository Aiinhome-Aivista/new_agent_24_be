import requests
import json

# Test login to get JWT
login_res = requests.post("http://localhost:5000/api/v1/login", json={
    "email": "developer@tdd.local",
    "password": "Passw0rd!"
})
if login_res.status_code != 200:
    # Try default credentials or create demo token
    print(f"Login failed: {login_res.status_code}, {login_res.text}")
    token = "demo"
else:
    token = login_res.json().get("data", {}).get("access_token")

headers = {"Authorization": f"Bearer {token}"}

# Load collection
with open("../ticket-management.postman_collection.json", "r", encoding="utf-8") as f:
    collection_data = json.load(f)

# Autonomous run request
res = requests.post("http://localhost:5000/api/v1/api-executor/autonomous-run", headers=headers, json={
    "base_url": "http://localhost:5001",
    "collection_json": collection_data,
    "collection_name": "Ticket Management API (2 endpoints)",
    "story_uuid": "2188b0fe-8673-4d57-a1f7-ad79bf38d0a4"
})

print("Status Code:", res.status_code)
data = res.json()
print("Success:", data.get("success"))
if data.get("success"):
    ev = data.get("data", {})
    print("Evidence Key:", ev.get("evidence_key"))
    print("Recommendation:", ev.get("recommendation"))
    print("Anomalies Count:", len(ev.get("anomalies", [])))
    print("Total Endpoints Tested:", len(ev.get("results", [])))
    for r in ev.get("results", []):
        print(f"  [{r.get('status_code')}] {r.get('test_key')} -> Passed: {r.get('passed')} (Deviations: {len(r.get('deviations', []))})")
        if not r.get('passed') or len(r.get('deviations', [])) > 0:
            print(f"     REQ: {r.get('request')}")
            print(f"     RESP: {r.get('response')}")
            print(f"     DEVS: {r.get('deviations')}")
else:
    print("Error:", data)
