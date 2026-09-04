import uuid
from app.agents.base import BaseAgent
from app.tools.api_runner.runner import get_runner
from app.repositories.test_repo import save_execution_run_with_results
from app.workflows.state_machine import CODE_VALIDATION


class ApiExecutorAgent(BaseAgent):
    """Deterministic execution only. The LLM never produces execution values."""
    name = "api_executor"

    def run(self, workflow_id, state):
        from app.repositories.test_repo import list_test_cases
        runner = get_runner()
        collection = state.get("collection_path")
        environment = state.get("environment", "default")
        test_cases = list_test_cases(workflow_id) or state.get("generated_tests", [])

        run = runner.run(collection, environment, test_cases=test_cases)
        passed = sum(1 for r in run.results if r["passed"])
        failed = len(run.results) - passed

        run_id = save_execution_run_with_results(
            str(uuid.uuid4()), workflow_id,
            runner="mock" if run.is_mock else "newman",
            environment=environment, collection=collection or "n/a",
            status="COMPLETED", total=len(run.results), passed=passed, failed=failed,
            is_mock=1 if run.is_mock else 0,
            results=run.results
        )

        state["execution"] = {"run_id": run_id, "total": len(run.results),
                              "passed": passed, "failed": failed, "is_mock": run.is_mock}
        state["current_stage"] = CODE_VALIDATION
        self._record(workflow_id, "api_execution", tool_name="api_runner",
                     output_summary={"total": len(run.results), "passed": passed, "failed": failed})
        return state
