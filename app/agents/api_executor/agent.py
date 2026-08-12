import uuid
from app.agents.base import BaseAgent
from app.tools.api_runner.runner import get_runner
from app.repositories.test_repo import (create_execution_run, add_execution_result,
                                         save_raw_request, save_raw_response)
from app.workflows.state_machine import CODE_VALIDATION


class ApiExecutorAgent(BaseAgent):
    """Deterministic execution only. The LLM never produces execution values."""
    name = "api_executor"

    def run(self, workflow_id, state):
        runner = get_runner()
        collection = state.get("collection_path")
        environment = state.get("environment", "default")

        run = runner.run(collection, environment)
        passed = sum(1 for r in run.results if r["passed"])
        failed = len(run.results) - passed

        run_id = create_execution_run(
            str(uuid.uuid4()), workflow_id,
            runner="mock" if run.is_mock else "newman",
            environment=environment, collection=collection or "n/a",
            status="COMPLETED", total=len(run.results), passed=passed, failed=failed,
            is_mock=1 if run.is_mock else 0)

        for r in run.results:
            res_id = add_execution_result(
                str(uuid.uuid4()), run_id, None, r["status_code"], 1 if r["passed"] else 0,
                r["duration_ms"], r["assertions"], 1 if run.is_mock else 0)
            save_raw_request(res_id, r["request"]["method"], r["request"]["url"], {}, None)
            save_raw_response(res_id, r["status_code"], {}, r.get("response_body"), None)

        state["execution"] = {"run_id": run_id, "total": len(run.results),
                              "passed": passed, "failed": failed, "is_mock": run.is_mock}
        state["current_stage"] = CODE_VALIDATION
        self._record(workflow_id, "api_execution", tool_name="api_runner",
                     output_summary={"total": len(run.results), "passed": passed, "failed": failed})
        return state
