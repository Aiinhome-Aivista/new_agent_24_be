"""Workflow run / task / agent-run persistence."""
import json
from app.extensions.db import query, execute


def _dumps(obj):
    return json.dumps(obj, default=str)


def create_run(workflow_id, project_id, story_id, status, stage, capabilities, state, started_by):
    execute("""INSERT INTO workflow_runs
               (workflow_id, project_id, story_id, status, current_stage, capabilities, state_json, started_by, started_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())""",
            (workflow_id, project_id, story_id, status, stage,
             _dumps(capabilities), _dumps(state), started_by))


def update_run(workflow_id, status, stage, state, current_agent=None, error_code=None, error_message=None):
    execute("""UPDATE workflow_runs
               SET status=%s, current_stage=%s, current_agent=%s, state_json=%s,
                   error_code=%s, error_message=%s,
                   completed_at = CASE WHEN %s IN ('COMPLETED','FAILED','CANCELLED') THEN NOW() ELSE completed_at END
               WHERE workflow_id=%s""",
            (status, stage, current_agent, _dumps(state), error_code, error_message, status, workflow_id))



def get_run(workflow_id):
    row = query("SELECT * FROM workflow_runs WHERE workflow_id=%s", (workflow_id,), fetchone=True)
    if row and isinstance(row.get("state_json"), str):
        row["state_json"] = json.loads(row["state_json"] or "{}")
    return row


def list_runs(project_uuid=None):
    if project_uuid:
        return query("""SELECT w.* FROM workflow_runs w JOIN projects p ON p.id=w.project_id
                        WHERE p.uuid=%s ORDER BY w.created_at DESC""", (project_uuid,))
    return query("SELECT * FROM workflow_runs ORDER BY created_at DESC")


def record_agent_run(uuid, workflow_id, agent, task_type, model_name, tool_name,
                     status, input_summary, output_summary, latency_ms, trace_id):
    execute("""INSERT INTO agent_runs
               (uuid, workflow_id, agent, task_type, model_name, tool_name, status,
                input_summary, output_summary, latency_ms, trace_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (uuid, workflow_id, agent, task_type, model_name, tool_name, status,
             _dumps(input_summary or {}), _dumps(output_summary or {}), latency_ms, trace_id))



def list_agent_runs(workflow_id=None):
    if workflow_id:
        return query("SELECT * FROM agent_runs WHERE workflow_id=%s ORDER BY created_at ASC", (workflow_id,))
    return query("SELECT * FROM agent_runs ORDER BY created_at DESC LIMIT 100")
