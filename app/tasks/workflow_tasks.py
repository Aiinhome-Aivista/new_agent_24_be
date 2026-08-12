"""
Async workflow tasks. Retries use exponential backoff with a retry limit; on exhaustion
the run is marked FAILED (dead-letter persisted in workflow_runs.error_*). ALM writes are
NOT blindly retried — the ALM agent's idempotency key guards duplicates.
"""
from app.tasks.celery_app import celery_app
from app.agents.orchestrator.orchestrator import Orchestrator
from app.repositories.workflow_repo import get_run, update_run
from app.config import Config
from app.workflows.state_machine import FAILED

orchestrator = Orchestrator()


@celery_app.task(bind=True, max_retries=Config.WORKFLOW_MAX_RETRIES)
def run_workflow_task(self, workflow_id, initial_state):
    try:
        return orchestrator.advance(workflow_id, initial_state)
    except Exception as exc:  # noqa: BLE001
        if self.request.retries >= self.max_retries:
            run = get_run(workflow_id)
            state = run["state_json"] if run else initial_state
            update_run(workflow_id, FAILED, state.get("current_stage", "CREATED"), state,
                       error_code="TASK_FAILED", error_message=str(exc)[:900])
            return {"status": FAILED, "error": str(exc)}
        raise self.retry(exc=exc, countdown=10 * (2 ** self.request.retries))


@celery_app.task(bind=True, max_retries=Config.WORKFLOW_MAX_RETRIES)
def resume_workflow_task(self, workflow_id, checkpoint):
    run = get_run(workflow_id)
    if not run:
        return {"error": "workflow not found"}
    state = run["state_json"]
    try:
        return orchestrator.resume(workflow_id, state, checkpoint)
    except Exception as exc:  # noqa: BLE001
        if self.request.retries >= self.max_retries:
            update_run(workflow_id, FAILED, checkpoint, state,
                       error_code="RESUME_FAILED", error_message=str(exc)[:900])
            return {"status": FAILED, "error": str(exc)}
        raise self.retry(exc=exc, countdown=10 * (2 ** self.request.retries))
