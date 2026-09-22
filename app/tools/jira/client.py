"""
Jira Cloud REST API Client and Story Extractor.
Integrates with Jira Cloud (REST API v3) to fetch stories/features, parse Atlassian Document Format (ADF),
and extract structured user stories and Acceptance Criteria for Agent-24 workflows.
"""
import os
import time
from datetime import datetime, timezone, timedelta
import re
import requests
from requests.auth import HTTPBasicAuth
from typing import Dict, Any, List, Optional
from app.config import Config
from app.tools.story_extractor.extractor import StoryDocumentExtractor


def adf_to_markdown(node: Any) -> str:
    """
    Recursively converts Atlassian Document Format (ADF) JSON structure
    into clean GitHub-Flavored Markdown.
    """
    if not node:
        return ""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return str(node)

    ntype = node.get("type", "")
    content = node.get("content", [])

    if ntype == "text":
        text = node.get("text", "")
        marks = node.get("marks", [])
        for m in marks:
            mtype = m.get("type") if isinstance(m, dict) else str(m)
            if mtype == "code":
                text = f"`{text}`"
            elif mtype == "strong":
                text = f"**{text}**"
            elif mtype == "em":
                text = f"*{text}*"
            elif mtype == "strike":
                text = f"~~{text}~~"
            elif mtype == "link":
                href = m.get("attrs", {}).get("href", "")
                text = f"[{text}]({href})"
        return text

    if ntype == "hardBreak":
        return "\n"

    inner_texts = [adf_to_markdown(c) for c in content]

    if ntype in ("doc", "paragraph"):
        return "".join(inner_texts) + "\n\n"
    elif ntype == "heading":
        lvl = "#" * max(1, min(6, node.get("attrs", {}).get("level", 2)))
        return f"{lvl} " + "".join(inner_texts) + "\n\n"
    elif ntype == "bulletList":
        items = []
        for c in content:
            c_text = adf_to_markdown(c).strip()
            if c_text:
                items.append(f"- {c_text}")
        return "\n".join(items) + "\n\n"
    elif ntype == "orderedList":
        items = []
        for i, c in enumerate(content, 1):
            c_text = adf_to_markdown(c).strip()
            if c_text:
                items.append(f"{i}. {c_text}")
        return "\n".join(items) + "\n\n"
    elif ntype == "listItem":
        return "".join(inner_texts).strip()
    elif ntype == "codeBlock":
        lang = node.get("attrs", {}).get("language", "")
        return f"```{lang}\n" + "".join(inner_texts) + "\n```\n\n"
    elif ntype == "rule":
        return "---\n\n"
    elif ntype == "blockquote":
        return "> " + "\n> ".join("".join(inner_texts).strip().split("\n")) + "\n\n"
    else:
        return "".join(inner_texts)


class JiraClient:
    """
    Client for interacting with Atlassian Jira Cloud REST API.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        email: Optional[str] = None,
        api_token: Optional[str] = None,
        project_key: Optional[str] = None,
        timeout: int = 15,
    ):
        self.base_url = (base_url or Config.JIRA_BASE_URL or "").strip().rstrip("/")
        self.email = (email or Config.JIRA_USER_EMAIL or "").strip()
        self.api_token = (api_token or Config.JIRA_API_TOKEN or "").strip()
        self.project_key = (project_key or Config.JIRA_PROJECT_KEY or "SCRUM").strip().upper()
        self.timeout = timeout

        self.auth = HTTPBasicAuth(self.email, self.api_token) if (self.email and self.api_token) else None
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}

    def is_configured(self) -> bool:
        return bool(self.base_url and self.email and self.api_token)

    def test_connection(self) -> Dict[str, Any]:
        """Validates Jira credentials against /rest/api/3/myself."""
        if not self.is_configured():
            return {
                "connected": False,
                "error": "Jira credentials are not fully configured (missing URL, email, or token).",
            }
        try:
            url = f"{self.base_url}/rest/api/3/myself"
            resp = requests.get(url, auth=self.auth, headers=self.headers, timeout=self.timeout)
            if resp.status_code == 200:
                user_data = resp.json()
                return {
                    "connected": True,
                    "display_name": user_data.get("displayName"),
                    "email": user_data.get("emailAddress"),
                    "account_id": user_data.get("accountId"),
                    "base_url": self.base_url,
                    "project_key": self.project_key,
                }
            elif resp.status_code == 401:
                return {
                    "connected": False,
                    "error": "Authentication failed (HTTP 401). Please verify your Jira Email and API Token.",
                }
            else:
                return {
                    "connected": False,
                    "error": f"Jira returned HTTP {resp.status_code}: {resp.text[:200]}",
                }
        except Exception as e:
            return {"connected": False, "error": str(e)}

    def get_issue(self, issue_key: str) -> Dict[str, Any]:
        """
        Fetches an individual issue from Jira and converts it into a structured
        User Story with Acceptance Criteria.
        """
        clean_key = (issue_key or "").strip().upper()
        if not clean_key:
            raise ValueError("Jira issue key is required.")

        if not self.is_configured():
            raise ValueError("Jira credentials not configured in backend.")

        url = f"{self.base_url}/rest/api/3/issue/{clean_key}"
        resp = requests.get(url, auth=self.auth, headers=self.headers, timeout=self.timeout)

        if resp.status_code == 404:
            raise ValueError(f"Jira issue '{clean_key}' not found or access denied.")
        elif resp.status_code == 401:
            raise ValueError("Jira authentication failed. Check your API Token.")
        resp.raise_for_status()

        issue_json = resp.json()
        return self._transform_jira_issue_to_story(issue_json)

    def list_issues(self, project_key: Optional[str] = None, max_results: int = 30) -> List[Dict[str, Any]]:
        """
        Fetches recent stories, features, and user requirements from the given Jira project.
        Excludes Bugs, Epics, and Sub-tasks to focus strictly on actionable User Stories.
        """
        target_project = (project_key or self.project_key or "SCRUM").strip().upper()
        if not self.is_configured():
            return []

        # JQL strictly targeting user stories, features, tasks, and requirements (excluding bugs & subtasks)
        jql = f"project = '{target_project}' AND issuetype not in ('Bug', 'Sub-task', 'Epic') ORDER BY updated DESC"
        
        # Try both Jira Search endpoints for backwards/forwards compatibility
        endpoints = [
            f"{self.base_url}/rest/api/3/search/jql",
            f"{self.base_url}/rest/api/3/search",
        ]

        issues_data = []
        for ep in endpoints:
            try:
                if "search/jql" in ep:
                    resp = requests.post(
                        ep,
                        auth=self.auth,
                        headers=self.headers,
                        json={"jql": jql, "maxResults": max_results, "fields": ["summary", "issuetype", "status", "updated", "priority", "description"]},
                        timeout=self.timeout
                    )
                else:
                    resp = requests.get(
                        ep,
                        auth=self.auth,
                        headers=self.headers,
                        params={"jql": jql, "maxResults": max_results, "fields": "summary,issuetype,status,updated,priority,description"},
                        timeout=self.timeout
                    )

                if resp.status_code == 200:
                    data = resp.json()
                    raw_issues = data.get("issues", [])
                    for i in raw_issues:
                        f = i.get("fields", {})
                        itype = f.get("issuetype", {}).get("name", "Story")
                        # Secondary filter to ensure no bug or sub-task leaks through
                        if itype.lower() in ("bug", "sub-task", "subtask", "epic"):
                            continue
                        issues_data.append({
                            "key": i.get("key"),
                            "summary": f.get("summary"),
                            "issue_type": itype,
                            "status": f.get("status", {}).get("name", "To Do"),
                            "priority": f.get("priority", {}).get("name", "Medium"),
                            "updated": f.get("updated"),
                        })
                    if issues_data:
                        break
            except Exception as e:
                print(f"[JiraClient] List issues failed on {ep}: {e}")

        return issues_data

    def _transform_jira_issue_to_story(self, issue_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Converts Jira Issue JSON into structured Agent-24 story payload.
        """
        fields = issue_json.get("fields", {})
        key = issue_json.get("key", "")
        summary = fields.get("summary", "")

        # 1. Convert description ADF to Markdown text
        raw_desc = fields.get("description")
        desc_md = ""
        if isinstance(raw_desc, dict):
            desc_md = adf_to_markdown(raw_desc).strip()
        elif isinstance(raw_desc, str):
            desc_md = raw_desc.strip()

        # 2. Extract Sprint if present
        sprint_name = "Sprint 1"
        sprint_field = fields.get("sprint")
        if isinstance(sprint_field, dict) and sprint_field.get("name"):
            sprint_name = sprint_field["name"]
        elif isinstance(sprint_field, list) and sprint_field and isinstance(sprint_field[0], dict):
            sprint_name = sprint_field[0].get("name", "Sprint 1")

        # 3. Parse Acceptance Criteria using StoryDocumentExtractor (heuristic + LLM)
        doc_content = f"# [{key}] {summary}\n\n## Sprint\n{sprint_name}\n\n{desc_md}"
        extracted = StoryDocumentExtractor.extract_from_file(
            doc_content.encode("utf-8"),
            filename=f"{key}.md",
            use_llm=True
        )

        acs = extracted.get("acceptance_criteria", [])
        clean_desc = extracted.get("description", "") or desc_md

        return {
            "title": summary or extracted.get("title") or key,
            "external_key": key,
            "sprint": sprint_name,
            "description": clean_desc,
            "acceptance_criteria": acs,
            "jira_url": f"{self.base_url}/browse/{key}",
            "issue_type": fields.get("issuetype", {}).get("name", "Feature"),
            "status": fields.get("status", {}).get("name", "To Do"),
            "extracted_count": len(acs),
        }

    def add_comment(self, issue_key: str, comment_text: str = None, adf_content: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Posts a comment to a Jira issue using Atlassian Document Format (ADF).
        """
        clean_key = (issue_key or "").strip().upper()
        if not clean_key:
            raise ValueError("Jira issue key is required.")
        if not self.is_configured():
            raise ValueError("Jira credentials not configured in backend.")

        url = f"{self.base_url}/rest/api/3/issue/{clean_key}/comment"

        if adf_content:
            payload = {"body": adf_content}
        else:
            payload = {
                "body": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": str(comment_text or "")}]
                        }
                    ]
                }
            }

        resp = requests.post(url, auth=self.auth, headers=self.headers, json=payload, timeout=self.timeout)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Failed to post Jira comment (HTTP {resp.status_code}): {resp.text[:300]}")
        return resp.json()

    @staticmethod
    def generate_evidence_attachment_name(
        project_name: Optional[str] = None,
        evidence_key: Optional[str] = None,
        execution_timestamp: Optional[str] = None,
    ) -> str:
        """
        Generates an enterprise-compliant attachment filename formatted with:
        <Project_Name>_<Evidence_Key>_<YYYY-MM-DD_HH-MM-SS_IST>.docx
        """
        # IST is UTC + 5:30
        IST = timezone(timedelta(hours=5, minutes=30))
        if execution_timestamp:
            try:
                dt = datetime.fromisoformat(str(execution_timestamp).replace("Z", "+00:00")).astimezone(IST)
            except Exception:
                dt = datetime.now(IST)
        else:
            dt = datetime.now(IST)

        ist_time_str = dt.strftime("%Y-%m-%d_%H-%M-%S_IST")

        parts = []
        if project_name:
            clean_proj = re.sub(r"[^\w]+", "_", str(project_name).strip())
            clean_proj = re.sub(r"_+", "_", clean_proj).strip("_")
            if clean_proj:
                parts.append(clean_proj)

        parts.append(evidence_key or "EVID-AUTO")
        parts.append(ist_time_str)

        return f"{'_'.join(parts)}.docx"

    def upload_attachment(
        self,
        issue_key: str,
        file_path: str,
        custom_filename: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Uploads a file attachment to a Jira issue.
        """
        clean_key = (issue_key or "").strip().upper()
        if not clean_key:
            raise ValueError("Jira issue key is required.")
        if not self.is_configured():
            raise ValueError("Jira credentials not configured in backend.")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Attachment file not found: {file_path}")

        url = f"{self.base_url}/rest/api/3/issue/{clean_key}/attachments"
        headers = {"X-Atlassian-Token": "nocheck"}

        filename = custom_filename or os.path.basename(file_path)
        with open(file_path, "rb") as f:
            files = {"file": (filename, f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
            resp = requests.post(url, auth=self.auth, headers=headers, files=files, timeout=45)

        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Failed to upload Jira attachment (HTTP {resp.status_code}): {resp.text[:300]}")
        return resp.json()

    def build_verification_report_adf(
        self,
        evidence_data: Dict[str, Any],
        approval_comment: Optional[str] = None,
        approver_name: Optional[str] = None,
        attachment_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Builds rich Atlassian Document Format (ADF) representation of an autonomous verification report.
        """
        rec = evidence_data.get("summary_recommendation", "API conforms")
        status_label = rec.upper()
        total_eps = evidence_data.get("total_endpoints", 0)
        passed_eps = evidence_data.get("passed_endpoints", 0)
        failed_eps = evidence_data.get("failed_endpoints", 0)
        total_devs = evidence_data.get("total_deviations", 0)
        evidence_key = evidence_data.get("evidence_key", "EVID-AUTO")
        trace_id = evidence_data.get("traceability_id", "TRC-N/A")
        sha256_seal = evidence_data.get("sha256_seal", "N/A")
        target_host = evidence_data.get("target_host") or "N/A"
        col_name = evidence_data.get("collection_name", "Test Collection")

        is_conforming = "conforms" in rec.lower() and "partially" not in rec.lower()
        is_partial = "partially" in rec.lower()
        panel_type = "success" if is_conforming else ("warning" if is_partial else "error")

        pass_rate_pct = int((passed_eps / total_eps) * 100) if total_eps > 0 else 100
        summary_badge = f"AUTONOMOUS VERIFICATION: {status_label} ({passed_eps}/{total_eps} Passed — {pass_rate_pct}%, {total_devs} Anomalies)"

        content = [
            {
                "type": "panel",
                "attrs": {"panelType": panel_type},
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": summary_badge, "marks": [{"type": "strong"}]}
                        ]
                    },
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": evidence_data.get("decision_summary", f"{passed_eps}/{total_eps} test scenarios passed. Detailed telemetry attached.")}
                        ]
                    }
                ]
            },
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": f"📊 Audit Evidence Telemetry — [{evidence_key}]"}]
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [{
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Target API Host: ", "marks": [{"type": "strong"}]},
                                {"type": "text", "text": str(target_host), "marks": [{"type": "code"}]}
                            ]
                        }]
                    },
                    {
                        "type": "listItem",
                        "content": [{
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Postman Collection / Contract: ", "marks": [{"type": "strong"}]},
                                {"type": "text", "text": str(col_name)}
                            ]
                        }]
                    },
                    {
                        "type": "listItem",
                        "content": [{
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Traceability ID: ", "marks": [{"type": "strong"}]},
                                {"type": "text", "text": str(trace_id), "marks": [{"type": "code"}]}
                            ]
                        }]
                    },
                    {
                        "type": "listItem",
                        "content": [{
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "SHA-256 Seal: ", "marks": [{"type": "strong"}]},
                                {"type": "text", "text": str(sha256_seal[:32]) + "...", "marks": [{"type": "code"}]}
                            ]
                        }]
                    },
                    {
                        "type": "listItem",
                        "content": [{
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Authorized Approver: ", "marks": [{"type": "strong"}]},
                                {"type": "text", "text": str(approver_name or "QA Lead Reviewer")}
                            ]
                        }]
                    },
                    {
                        "type": "listItem",
                        "content": [{
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Review Notes: ", "marks": [{"type": "strong"}]},
                                {"type": "text", "text": str(approval_comment or "Verified against story Acceptance Criteria.")}
                            ]
                        }]
                    }
                ]
            },
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": "🧪 Executed Acceptance Criteria Breakdown"}]
            }
        ]

        # Add list of executed test cases
        results = evidence_data.get("results", [])
        tc_items = []
        for idx, r in enumerate(results):
            m = r.get("method", "GET")
            status = r.get("status_code", 200)
            passed = r.get("passed", True)
            key = r.get("test_key") or f"Case #{idx+1}"
            icon = "✅" if passed else "❌"
            tc_items.append({
                "type": "listItem",
                "content": [{
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": f"{icon} "},
                        {"type": "text", "text": f"[{m}] ", "marks": [{"type": "strong"}]},
                        {"type": "text", "text": f"{key} — HTTP {status} (Passed: {passed})"}
                    ]
                }]
            })

        if tc_items:
            content.append({"type": "bulletList", "content": tc_items})

        # Add attachment notice
        display_filename = attachment_filename or f"{evidence_key}.docx"
        content.append({
            "type": "panel",
            "attrs": {"panelType": "info"},
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "📎 Attached Evidence Package: ", "marks": [{"type": "strong"}]},
                        {"type": "text", "text": display_filename, "marks": [{"type": "code"}]},
                        {"type": "text", "text": f" (Word document with {len(results)} Postman UI visual screenshots embedded in Section 4.1)."}
                    ]
                }
            ]
        })

        return {
            "type": "doc",
            "version": 1,
            "content": content
        }

    def sync_evidence_package(
        self,
        issue_key: str,
        evidence_data: Dict[str, Any],
        docx_path: Optional[str] = None,
        approval_comment: Optional[str] = None,
        approver_name: Optional[str] = None,
        custom_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Complete synchronization: posts formatted test evidence ADF comment and
        uploads the signed .docx package attachment to the specified Jira Story.
        """
        clean_key = (issue_key or "").strip().upper()
        if not clean_key:
            raise ValueError("Jira Story / Issue key is required.")

        evidence_key = evidence_data.get("evidence_key", "EVID-AUTO")
        project_name = evidence_data.get("project_name")
        execution_timestamp = evidence_data.get("execution_timestamp")

        if not custom_filename:
            custom_filename = self.generate_evidence_attachment_name(
                project_name=project_name,
                evidence_key=evidence_key,
                execution_timestamp=execution_timestamp,
            )

        # 1. Post Comment with ADF report
        adf_body = self.build_verification_report_adf(
            evidence_data=evidence_data,
            approval_comment=approval_comment,
            approver_name=approver_name,
            attachment_filename=custom_filename,
        )
        comment_res = self.add_comment(clean_key, adf_content=adf_body)
        comment_id = comment_res.get("id")

        # 2. Upload .docx Attachment if path provided and exists
        attachment_info = None
        if docx_path and os.path.exists(docx_path):
            try:
                att_res = self.upload_attachment(clean_key, docx_path, custom_filename=custom_filename)
                if att_res and isinstance(att_res, list) and len(att_res) > 0:
                    attachment_info = att_res[0]
            except Exception as att_err:
                print(f"[JiraClient] Notice: attachment upload warning: {att_err}")

        IST = timezone(timedelta(hours=5, minutes=30))
        return {
            "success": True,
            "issue_key": clean_key,
            "jira_url": f"{self.base_url}/browse/{clean_key}",
            "comment_id": comment_id,
            "attachment": attachment_info,
            "filename": custom_filename,
            "synced_at": datetime.now(IST).isoformat(),
        }
