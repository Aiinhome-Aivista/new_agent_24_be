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


def get_alm_adapter():
    # Real adapters registered here per Config.ALM_PROVIDER; MOCK by default.
    return MockAlmAdapter()
