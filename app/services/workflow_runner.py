"""
Dispatch helper. Uses Celery when a broker is reachable; otherwise runs the workflow
inline (development convenience) so the platform is demoable without a worker process.
"""
import uuid
from app.tasks.workflow_tasks import run_workflow_task, resume_workflow_task
from app.agents.orchestrator.orchestrator import Orchestrator
from app.config import Config

_orchestrator = Orchestrator()


def _broker_available():
    try:
        import redis
        redis.from_url(Config.CELERY_BROKER_URL).ping()
        return True
    except Exception:
        return False


def dispatch_start(workflow_id, state):
    if _broker_available():
        task = run_workflow_task.delay(workflow_id, state)
        return task.id, "QUEUED"
    _orchestrator.advance(workflow_id, state)   # inline
    return f"inline-{uuid.uuid4().hex[:8]}", "RUNNING"


def dispatch_resume(workflow_id, checkpoint):
    if _broker_available():
        task = resume_workflow_task.delay(workflow_id, checkpoint)
        return task.id, "RESUMING"
    from app.repositories.workflow_repo import get_run
    run = get_run(workflow_id)
    _orchestrator.resume(workflow_id, run["state_json"], checkpoint)
    return f"inline-{uuid.uuid4().hex[:8]}", "RESUMING"
