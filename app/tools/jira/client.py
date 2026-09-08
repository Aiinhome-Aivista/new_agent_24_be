"""
Jira Cloud REST API Client and Story Extractor.
Integrates with Jira Cloud (REST API v3) to fetch stories/features, parse Atlassian Document Format (ADF),
and extract structured user stories and Acceptance Criteria for Agent-24 workflows.
"""
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
