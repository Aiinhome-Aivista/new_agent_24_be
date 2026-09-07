import uuid
import os
import urllib.parse
from app.agents.base import BaseAgent
from app.tools.api_runner.runner import get_runner
from app.repositories.test_repo import save_execution_run_with_results
from app.workflows.state_machine import CODE_VALIDATION


class ApiExecutorAgent(BaseAgent):
    """Automated Newman & API execution engine with dynamic URL resolution, live server boot, and visual screenshot evidence capture."""
    name = "api_executor"

    def run(self, workflow_id, state):
        from app.repositories.test_repo import list_test_cases
        project = state.get("project") or {}
        workspace_path = state.get("workspace_path")
        force_live = state.get("force_live_execution", False)

        # 1. Resolve Target URL: Deployed Branch / Environment vs. Localhost
        environment = state.get("environment") or project.get("base_url") or project.get("api_base_url") or project.get("environment_url")
        
        # If no explicit environment URL provided, detect from Git workspace or default to localhost:8080
        if not environment:
            if workspace_path and os.path.isdir(workspace_path):
                try:
                    from app.tools.repository.workspace import GitWorkspace
                    project_uuid = project.get("uuid") or project.get("id") or "default"
                    ws = GitWorkspace(str(project_uuid), project.get("git_repo_url", ""))
                    environment = ws.detect_base_url()
                except Exception as e:
                    print(f"[ApiExecutor] Workspace URL detection note: {e}")
                    environment = "http://localhost:8080"
            else:
                environment = "http://localhost:8080"

        # 2. If Localhost and local workspace exists, ensure local app server is running
        if "localhost" in environment or "127.0.0.1" in environment:
            if workspace_path and os.path.isdir(workspace_path):
                parsed = urllib.parse.urlparse(environment)
                port = parsed.port if parsed.port else 8080
                try:
                    from app.tools.environment.live_runner import LiveEnvironmentManager
                    manager = LiveEnvironmentManager(workspace_path, port=port)
                    server_started = manager.start_server()
                    if server_started:
                        print(f"[ApiExecutor] Live local application server is active on {environment} for Newman execution.")
                except Exception as ex:
                    print(f"[ApiExecutor] LiveEnvironmentManager note: {ex}")

        # 3. Execute Newman / API runner
        runner = get_runner(force_live=force_live)
        collection = state.get("collection_path")
        test_cases = list_test_cases(workflow_id) or state.get("generated_tests", [])

        print(f"\n[ApiExecutor] Starting Automated Newman Execution for Workflow {workflow_id[:8]}...")
        print(f"[ApiExecutor] Target URL / Environment: {environment} | Total Tests: {len(test_cases)}")

        run = runner.run(collection, environment=environment, test_cases=test_cases, workflow_id=workflow_id)
        passed = sum(1 for r in run.results if r["passed"])
        failed = len(run.results) - passed

        print(f"[ApiExecutor] Newman Execution Finished: {passed}/{len(run.results)} Passed (Failed: {failed})")
        print(f"[ApiExecutor] Visual Screenshots captured for {len(run.results)} test cases.")

        run_id = save_execution_run_with_results(
            str(uuid.uuid4()), workflow_id,
            runner="mock" if run.is_mock else "newman",
            environment=environment, collection=collection or run.collection_path or "postman_collection.json",
            status="COMPLETED", total=len(run.results), passed=passed, failed=failed,
            is_mock=1 if run.is_mock else 0,
            results=run.results
        )

        state["execution"] = {
            "run_id": run_id,
            "total": len(run.results),
            "passed": passed,
            "failed": failed,
            "is_mock": run.is_mock,
            "results": run.results,
            "collection_path": run.collection_path,
            "environment": environment
        }
        state["current_stage"] = CODE_VALIDATION
        self._record(workflow_id, "api_execution", tool_name="api_runner",
                     output_summary={"total": len(run.results), "passed": passed, "failed": failed, "screenshots": len(run.results), "target_url": environment})
        return state
