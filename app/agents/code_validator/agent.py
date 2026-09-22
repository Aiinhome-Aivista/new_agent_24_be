"""
Code Validator Agent — Stage 9 (CODE_VALIDATION).

Responsibilities:
1. Execute the generated unit tests via pytest (real execution, not mock).
2. Measure actual code coverage via pytest-cov (line + branch coverage).
3. Persist all real results — NEVER fabricates test results or coverage numbers.
4. Advance workflow to EVIDENCE_GENERATION.
"""
import os
from pathlib import Path
from app.agents.base import BaseAgent
from app.workflows.state_machine import EVIDENCE_GENERATION


class CodeValidatorAgent(BaseAgent):
    """
    Code validation executes real unit tests with pytest-cov.
    Never fabricates test results or coverage numbers.
    """
    name = "code_validator"

    def run(self, workflow_id, state):
        # Code quality calculation removed per system specification.
        # Stage 9 focuses strictly on real unit test execution and real code coverage measurement.
        state["code_quality"] = None

        # -------------------------------------------------------------------
        # 1. Real Unit Test Execution + Code Coverage (pytest + coverage.py)
        # -------------------------------------------------------------------
        unit_test_result = self._run_unit_tests_with_coverage(workflow_id, state)
        unit_test_result["trace_data"] = {
            "test_command": unit_test_result.get("test_command", "pytest --cov"),
            "test_file_path": self._find_generated_test_file(workflow_id, state) or "N/A",
            "workspace": state.get("workspace_path", "N/A"),
            "total_tests": unit_test_result.get("total_tests", 0),
            "executed": unit_test_result.get("executed", False),
            "passed": unit_test_result.get("passed_tests", 0),
            "failed": unit_test_result.get("failed_tests", 0),
            "skipped": unit_test_result.get("skipped_tests", 0),
            "errors": unit_test_result.get("error_tests", 0),
            "exit_code": unit_test_result.get("exit_code", 0 if unit_test_result.get("failed_tests", 0) == 0 else 1),
            "execution_duration": unit_test_result.get("execution_time_seconds", 0.0),
        }
        state["unit_test_execution"] = unit_test_result

        # Merge real coverage into state so evidence generator can use it
        if unit_test_result.get("executed") and not unit_test_result.get("is_mock"):
            state["real_code_coverage"] = {
                "line_coverage_pct": unit_test_result.get("line_coverage_pct", 0.0),
                "branch_coverage_pct": unit_test_result.get("branch_coverage_pct", 0.0),
                "num_statements": unit_test_result.get("num_statements", 0),
                "num_missing": unit_test_result.get("num_missing", 0),
                "covered_files": unit_test_result.get("covered_files", []),
                "uncovered_files": unit_test_result.get("uncovered_files", []),
                "scoped_source_files": unit_test_result.get("scoped_source_files", []),
                "is_mock": False,
            }
            print(f"[CodeValidator] Real coverage — Line: {unit_test_result.get('line_coverage_pct')}% "
                  f"| Branch: {unit_test_result.get('branch_coverage_pct')}%")
        else:
            # Could not run real coverage (no test files, no workspace, etc.)
            state["real_code_coverage"] = {
                "line_coverage_pct": None,
                "branch_coverage_pct": None,
                "is_mock": True,
                "reason": unit_test_result.get("error_message", "Unit test execution not attempted"),
            }
            print(f"[CodeValidator] Could not run real coverage: {unit_test_result.get('error_message')}")

        # -------------------------------------------------------------------
        # 2. Advance to EVIDENCE_GENERATION
        # -------------------------------------------------------------------
        state["current_stage"] = EVIDENCE_GENERATION
        self._record(
            workflow_id,
            "code_validation",
            tool_name="pytest_cov",
            output_summary={
                "tests_total": unit_test_result.get("total_tests", 0),
                "tests_passed": unit_test_result.get("passed_tests", 0),
                "line_coverage_pct": state["real_code_coverage"].get("line_coverage_pct"),
            }
        )
        return state

    def _run_unit_tests_with_coverage(self, workflow_id: str, state: dict) -> dict:
        """
        Locate the generated test file for this workflow, then run it with
        pytest + coverage.py. Returns the CoverageResult as a dict.
        """
        # Locate the generated test file on disk
        test_file_path = self._find_generated_test_file(workflow_id, state)
        if not test_file_path:
            print(f"[CodeValidator] No generated test file found for workflow {workflow_id[:8]}")
            return {
                "executed": False,
                "is_mock": True,
                "error_message": "No generated test file found on disk for this workflow.",
                "total_tests": 0, "passed_tests": 0, "failed_tests": 0,
                "line_coverage_pct": None, "branch_coverage_pct": None,
            }

        # Collect relevant function names and mapped source files for coverage scoping
        test_cases = state.get("generated_tests", [])
        relevant_functions = []
        for tc in test_cases:
            relevant_functions.extend(tc.get("responsible_functions") or [])

        # Include responsible files from ac_api_code_mapping for precision scoping
        for m in (state.get("ac_api_code_mapping") or []):
            relevant_functions.extend(m.get("responsible_files") or [])

        workspace_path = state.get("workspace_path")
        if not workspace_path or not os.path.isdir(workspace_path):
            proj = state.get("project") or {}
            cand = proj.get("workspace_path") or proj.get("git_repo_url")
            if cand and os.path.isdir(cand):
                workspace_path = cand
            else:
                default_ws = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "simple_python_deploy"))
                if os.path.isdir(default_ws):
                    workspace_path = default_ws

        try:
            from app.tools.code_coverage.executor import get_coverage_executor
            executor = get_coverage_executor(timeout_seconds=90)
            result = executor.run(
                test_file_path=test_file_path,
                workspace_path=workspace_path,
                relevant_functions=relevant_functions,
            )
            return result.to_dict()
        except ImportError as e:
            # pytest-cov not installed — degrade gracefully
            print(f"[CodeValidator] pytest-cov not available: {e}. Skipping real coverage.")
            return {
                "executed": False,
                "is_mock": True,
                "error_message": f"pytest-cov not installed: {e}",
                "total_tests": 0, "passed_tests": 0, "failed_tests": 0,
                "line_coverage_pct": None, "branch_coverage_pct": None,
            }
        except Exception as e:
            print(f"[CodeValidator] Coverage execution error: {e}")
            return {
                "executed": False,
                "is_mock": True,
                "error_message": str(e),
                "total_tests": 0, "passed_tests": 0, "failed_tests": 0,
                "line_coverage_pct": None, "branch_coverage_pct": None,
            }

    def _find_generated_test_file(self, workflow_id: str, state: dict) -> str | None:
        """
        Locate the generated test file written by CodeGeneratorAgent.
        Checks:
        1. State code_generation.files_written, preferring workspace path
        2. Workspace tests directory for generated test suite
        3. evidence_output/generated_tests/<workflow_id>/ directory
        """
        ws_path = state.get("workspace_path")
        if not ws_path or not os.path.isdir(ws_path):
            proj = state.get("project") or {}
            cand = proj.get("workspace_path") or proj.get("git_repo_url")
            if cand and os.path.isdir(cand):
                ws_path = cand
            else:
                default_ws = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "simple_python_deploy"))
                if os.path.isdir(default_ws):
                    ws_path = default_ws

        # 1. Check state for files written by CodeGeneratorAgent, preferring workspace test file
        code_gen = state.get("code_generation") or {}
        files_written = code_gen.get("files_written") or []
        for fw in files_written:
            fpath = fw.get("file_path") or fw.get("relative_path")
            if fpath and ws_path and str(ws_path) in str(fpath) and os.path.isfile(fpath):
                return str(fpath)
        for fw in files_written:
            fpath = fw.get("file_path") or fw.get("relative_path")
            if fpath and os.path.isfile(fpath):
                return str(fpath)

        # 2. Check workspace tests directory
        if ws_path and os.path.isdir(ws_path):
            ws_tests = os.path.join(ws_path, "tests")
            if os.path.isdir(ws_tests):
                for fname in os.listdir(ws_tests):
                    if fname.startswith("test_") and fname != "test_api.py" and fname.endswith(".py"):
                        return os.path.join(ws_tests, fname)

        # 3. Scan evidence_output/generated_tests/<workflow_id>/
        evidence_test_dir = Path("evidence_output") / "generated_tests" / workflow_id
        if evidence_test_dir.is_dir():
            lang = (state.get("project") or {}).get("target_language", "python").lower()
            pattern = "*.py" if lang == "python" else f"*.{lang}"
            for p in sorted(evidence_test_dir.glob(pattern)):
                if p.is_file() and not p.name.startswith("conftest"):
                    return str(p.resolve())

        return None
