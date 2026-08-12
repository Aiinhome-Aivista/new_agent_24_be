"""
Guardrail engine: input, retrieval, execution, output, and ALM layers.
Each check returns (passed: bool, detail: str) and is logged to guardrail_events.
"""
import re
from app.audit.audit_log import guardrail

_INJECTION = ["ignore previous instructions", "disregard the system prompt",
              "you are now", "act as if you have no restrictions", "reveal your system prompt"]
_SECRET = [re.compile(r"(?i)api[_-]?key\s*[:=]\s*\S+"),
           re.compile(r"(?i)password\s*[:=]\s*\S+"),
           re.compile(r"(?i)bearer\s+[a-z0-9._\-]{20,}")]


def check_input(text, workflow_id=None):
    lowered = (text or "").lower()
    for marker in _INJECTION:
        if marker in lowered:
            guardrail("input", "prompt_injection", False, workflow_id, marker)
            return False, f"Possible prompt injection: {marker}"
    for pat in _SECRET:
        if pat.search(text or ""):
            guardrail("input", "secret_in_input", False, workflow_id, "redacted")
            return False, "Secret-like content detected in input"
    guardrail("input", "input_clean", True, workflow_id)
    return True, "ok"


def check_retrieval(chunk_project_id, requesting_project_id, workflow_id=None):
    ok = chunk_project_id == requesting_project_id
    guardrail("retrieval", "project_isolation", ok, workflow_id,
              None if ok else "cross-project retrieval blocked")
    return ok, "ok" if ok else "cross-project retrieval blocked"


def check_execution(tool_name, allowed_tools, workflow_id=None):
    ok = tool_name in allowed_tools
    guardrail("execution", "tool_allowed", ok, workflow_id, None if ok else tool_name)
    return ok, "ok" if ok else f"tool {tool_name} not allowed"


def check_output(structured, required_keys, workflow_id=None):
    missing = [k for k in required_keys if k not in (structured or {})]
    ok = not missing
    guardrail("output", "schema_valid", ok, workflow_id, None if ok else f"missing {missing}")
    return ok, "ok" if ok else f"missing fields: {missing}"


def check_alm(approved, idempotency_key, workflow_id=None):
    ok = bool(approved and idempotency_key)
    guardrail("alm", "approval_and_idempotency", ok, workflow_id,
              None if ok else "ALM write requires approval + idempotency key")
    return ok, "ok" if ok else "ALM write requires approval + idempotency key"
