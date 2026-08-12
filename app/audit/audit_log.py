"""Immutable-style audit records + guardrail event log. Never logs secrets."""
import uuid as _uuid
import json
from app.extensions.db import execute, query
from app.observability.tracing import redact


def record(event_type, *, user_id=None, project_id=None, story_id=None, workflow_id=None,
           agent=None, tool=None, status=None, metadata=None, trace_id=None, request_id=None):
    execute("""INSERT INTO audit_events
        (event_id, user_id, project_id, story_id, workflow_id, agent, tool, event_type, status, metadata, trace_id, request_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (str(_uuid.uuid4()), user_id, project_id, story_id, workflow_id, agent, tool,
         event_type, status, json.dumps(redact(metadata or {}), default=str), trace_id, request_id))



def guardrail(layer, rule, passed, workflow_id=None, detail=None):
    execute("""INSERT INTO guardrail_events (uuid, workflow_id, layer, rule, passed, detail)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (str(_uuid.uuid4()), workflow_id, layer, rule, 1 if passed else 0, detail))


def list_events(workflow_id=None, limit=200):
    if workflow_id:
        return query("SELECT * FROM audit_events WHERE workflow_id=%s ORDER BY timestamp DESC LIMIT %s",
                     (workflow_id, limit))
    return query("SELECT * FROM audit_events ORDER BY timestamp DESC LIMIT %s", (limit,))


def list_guardrail_events(workflow_id=None, limit=200):
    if workflow_id:
        return query("SELECT * FROM guardrail_events WHERE workflow_id=%s ORDER BY created_at DESC LIMIT %s",
                     (workflow_id, limit))
    return query("SELECT * FROM guardrail_events ORDER BY created_at DESC LIMIT %s", (limit,))
