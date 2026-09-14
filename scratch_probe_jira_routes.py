import requests

BASE_API = "http://localhost:5000/api/v1"
s = requests.Session()
r_login = s.post(f"{BASE_API}/login", json={"email": "developer@tdd.local", "password": "Passw0rd!"})
token = r_login.json().get("data", {}).get("access_token")
headers = {"Authorization": f"Bearer {token}"}

endpoints = [
    ("GET", f"{BASE_API}/health"),
    ("GET", f"{BASE_API}/jira/status"),
    ("GET", f"{BASE_API}/jira/stories"),
    ("POST", f"{BASE_API}/jira/sync-evidence"),
]

for m, u in endpoints:
    if m == "GET":
        r = s.get(u, headers=headers)
    else:
        r = s.post(u, headers=headers, json={"issue_key": "SCRUM-40"})
    print(f"{m} {u} -> Status {r.status_code}")
