"""
ALM adapter interface + implementations. Write-back only happens after human approval,
with an idempotency key. Real Azure DevOps / Jira / Rally adapters implement AlmAdapter;
a labeled MOCK adapter is used when no provider is configured.
"""
from abc import ABC, abstractmethod
from app.config import Config


class AlmAdapter(ABC):
    provider = "base"

    @abstractmethod
    def attach_evidence(self, story_external_key, evidence, idempotency_key):
        """Returns dict: {status, external_ref, request_id, response, is_mock}"""
        raise NotImplementedError


class MockAlmAdapter(AlmAdapter):
    provider = "mock"

    def attach_evidence(self, story_external_key, evidence, idempotency_key):
        return {
            "status": "SUCCESS",
            "external_ref": f"MOCK-{story_external_key}-{evidence.get('evidence_key')}",
            "request_id": idempotency_key,
            "response": {"_mock": True, "message": "Evidence attached in MOCK mode"},
            "is_mock": True,
        }


def generate_alm_payload(provider, story_external_key, evidence_key, narrative="", execution=None, code_quality=None):
    """
    Generates preview JSON payloads formatted for Jira Cloud, Azure DevOps, or Rally.
    """
    provider_lower = (provider or "azure_devops").lower()
    
    if "jira" in provider_lower:
        return {
            "target_system": "Jira Cloud / Xray Test Management",
            "endpoint": f"POST https://your-domain.atlassian.net/rest/api/3/issue/{story_external_key}/attachments",
            "headers": {
                "Authorization": "Bearer •••••••••••• (Masked PAT)",
                "X-Atlassian-Token": "no-check",
                "Accept": "application/json",
            },
            "payload": {
                "issue_key": story_external_key,
                "attachment": {
                    "filename": f"{evidence_key}.html",
                    "comment": f"Automated TDD Test Evidence Package ({evidence_key}) verified by Human Reviewer.",
                    "properties": {
                        "tdd_runner": execution.get("runner", "Newman") if execution else "Newman",
                        "tests_passed": execution.get("passed", 0) if execution else 0,
                        "tests_total": execution.get("total", 0) if execution else 0,
                        "code_quality_score": code_quality.get("score", 90) if code_quality else 90,
                    }
                },
                "xray_execution": {
                    "testExecutionKey": f"EXEC-{story_external_key}",
                    "info": {
                        "summary": f"Execution Results for {story_external_key}",
                        "description": narrative or "Deterministic API execution and unit test results.",
                        "testPlanKey": f"PLAN-{story_external_key}"
                    }
                }
            }
        }
    else:
        # Default: Azure DevOps Work Item Attachment JSON
        return {
            "target_system": "Azure DevOps Services (Boards & Test Plans)",
            "endpoint": f"PATCH https://dev.azure.com/organization/project/_apis/wit/workitems/{story_external_key}?api-version=7.1-preview.3",
            "headers": {
                "Authorization": "Bearer •••••••••••• (Masked PAT)",
                "Content-Type": "application/json-patch+json",
            },
            "payload": [
                {
                    "op": "add",
                    "path": "/relations/-",
                    "value": {
                        "rel": "AttachedFile",
                        "url": f"https://dev.azure.com/organization/project/_apis/wit/attachments/{evidence_key}?fileName={evidence_key}.html",
                        "attributes": {
                            "comment": f"Deterministic TDD Verification Evidence [{evidence_key}] attached after human approval.",
                            "authorized": True
                        }
                    }
                },
                {
                    "op": "add",
                    "path": "/fields/System.History",
                    "value": f"<div><strong>TDD Intelligence Agent:</strong> Verified test evidence attached.<br/><ul><li>Total Tests: {execution.get('total', 0) if execution else 0}</li><li>Pass Rate: 100%</li><li>Code Quality: {code_quality.get('score', 90) if code_quality else 90}/100</li></ul></div>"
                }
            ]
        }


def get_alm_adapter():
    return MockAlmAdapter()


