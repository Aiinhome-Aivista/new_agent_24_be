import requests
from requests.auth import HTTPBasicAuth
from app.config.settings import Config
import json
import os

def test_jira_comment_and_attachment():
    base_url = Config.JIRA_BASE_URL.rstrip('/')
    email = Config.JIRA_USER_EMAIL
    token = Config.JIRA_API_TOKEN
    auth = HTTPBasicAuth(email, token)
    
    issue_key = "SCRUM-40"
    
    # 1. Test Comment posting (ADF format)
    comment_url = f"{base_url}/rest/api/3/issue/{issue_key}/comment"
    adf_body = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "panel",
                    "attrs": {"panelType": "success"},
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "✅ AUTONOMOUS API VERIFICATION: API CONFORMS (8/8 Passed, 0 Anomalies)", "marks": [{"type": "strong"}]}
                            ]
                        }
                    ]
                },
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Evidence Package: ", "marks": [{"type": "strong"}]},
                        {"type": "text", "text": "EVID-AUTO-2B1BE044 (SHA-256 Seal verified)"}
                    ]
                }
            ]
        }
    }
    
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    resp = requests.post(comment_url, auth=auth, headers=headers, json=adf_body, timeout=15)
    print(f"Comment post status: {resp.status_code}")
    if resp.status_code in (200, 201):
        print("Comment ID:", resp.json().get("id"))
    else:
        print("Comment error:", resp.text)
        
    # 2. Test Attachment uploading
    attachment_url = f"{base_url}/rest/api/3/issue/{issue_key}/attachments"
    att_headers = {"X-Atlassian-Token": "nocheck", "Accept": "application/json"}
    
    test_docx = "../EVID-AUTO-2B1BE044.docx"
    if os.path.exists(test_docx):
        with open(test_docx, "rb") as f:
            files = {"file": (os.path.basename(test_docx), f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
            att_resp = requests.post(attachment_url, auth=auth, headers=att_headers, files=files, timeout=30)
            print(f"Attachment upload status: {att_resp.status_code}")
            if att_resp.status_code in (200, 201):
                att_data = att_resp.json()
                print("Uploaded attachments:", len(att_data))
                for a in att_data:
                    print(f"  - {a.get('filename')} (ID: {a.get('id')}, Size: {a.get('size')} bytes)")
            else:
                print("Attachment error:", att_resp.text)
    else:
        print(f"Test docx not found at {test_docx}")

if __name__ == "__main__":
    test_jira_comment_and_attachment()
