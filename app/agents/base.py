"""Base agent — structured I/O, audit + agent_run recording, id/time helpers."""
import uuid
import datetime
from app.repositories.workflow_repo import record_agent_run
from app.audit.audit_log import record as audit


class BaseAgent:
    name = "base"
    version = "v1"

    def run(self, workflow_id, state):
        raise NotImplementedError

    def _record(self, workflow_id, task_type, model_name=None, tool_name=None,
                status="COMPLETED", input_summary=None, output_summary=None, latency_ms=None):
        record_agent_run(str(uuid.uuid4()), workflow_id, self.name, task_type, model_name,
                         tool_name, status, input_summary, output_summary, latency_ms, None)
        audit("agent_invocation", workflow_id=workflow_id, agent=self.name,
              status=status, metadata={"task_type": task_type})

    @staticmethod
    def nid(prefix):
        return f"{prefix}-{uuid.uuid4().hex[:8]}"

    @staticmethod
    def now():
        return datetime.datetime.utcnow().isoformat() + "Z"
