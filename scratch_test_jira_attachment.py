import requests
from requests.auth import HTTPBasicAuth
from app.config.settings import Config
import os

def test_jira_attachment():
    base_url = Config.JIRA_BASE_URL.rstrip('/')
    email = Config.JIRA_USER_EMAIL
    token = Config.JIRA_API_TOKEN
    auth = HTTPBasicAuth(email, token)
    
    issue_key = "SCRUM-40"
    attachment_url = f"{base_url}/rest/api/3/issue/{issue_key}/attachments"
    att_headers = {"X-Atlassian-Token": "nocheck", "Accept": "application/json"}
    
    candidates = [
        "evidence_output/EVID-AUTO-2B1BE044.docx",
        "../EVID-AUTO-2B1BE044.docx",
        "evidence_output/EVID-AUTO-9BF6C857.docx",
        "../EVID-AUTO-9BF6C857.docx"
    ]
    
    docx_path = None
    for c in candidates:
        if os.path.exists(c):
            docx_path = c
            break
            
    if docx_path:
        print(f"Uploading {docx_path} (Size: {os.path.getsize(docx_path):,} bytes)...")
        with open(docx_path, "rb") as f:
            files = {"file": (os.path.basename(docx_path), f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
            att_resp = requests.post(attachment_url, auth=auth, headers=att_headers, files=files, timeout=30)
            print(f"Attachment upload status: {att_resp.status_code}")
            if att_resp.status_code in (200, 201):
                att_data = att_resp.json()
                print("Uploaded attachments count:", len(att_data))
                for a in att_data:
                    print(f"  - {a.get('filename')} (ID: {a.get('id')}, Size: {a.get('size')} bytes, URL: {a.get('content')})")
            else:
                print("Attachment error:", att_resp.text)
    else:
        print("No docx file found in candidates.")

if __name__ == "__main__":
    test_jira_attachment()
