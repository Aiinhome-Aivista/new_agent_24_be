"""
Code Validator Agent — Stage 9 (CODE_VALIDATION).

Responsibilities:
1. Execute the generated unit tests via pytest (real execution, not mock).
2. Measure actual code coverage via pytest-cov (line + branch coverage).
3. Run static code quality analysis (SonarQube/mock).
4. Persist all real results — NEVER fabricates test results or coverage numbers.
5. Advance workflow to EVIDENCE_GENERATION.
"""
import os
import uuid
from pathlib import Path
from app.agents.base import BaseAgent
from app.tools.code_analysis.analyzer import get_analyzer
from app.llm.model_router.router import get_router
from app.repositories.test_repo import save_code_quality_run_with_issues
from app.workflows.state_machine import EVIDENCE_GENERATION


class CodeValidatorAgent(BaseAgent):
    """
    Static tools and coverage.py are authoritative.
    LLM only explains findings — never produces execution values.
    """
    name = "code_validator"

    def run(self, workflow_id, state):
        # -------------------------------------------------------------------
        # 1. Static Code Quality Analysis (SonarQube / mock)
        # -------------------------------------------------------------------
        analyzer = get_analyzer()
        code_units = [t.get("generated_code") for t in state.get("generated_tests", []) if t.get("generated_code")]
        analysis = analyzer.analyze(code_units)

        cq_id = save_code_quality_run_with_issues(
            str(uuid.uuid4()), workflow_id,
            "mock" if analysis.is_mock else "sonarqube",
            analysis.score, analysis.passed, analysis.is_mock,
            issues=analysis.issues
        )

        explanation = ""
        if analysis.issues:
            try:
                explanation = get_router().generate_text(
                    "explanation",
                    prompt=f"Briefly explain these code quality findings for a developer: {analysis.issues[:3]}"
                ).text
            except Exception:
                pass

        state["code_quality"] = {
            "score": analysis.score,
            "passed": analysis.passed,
            "issues": analysis.issues,
            "explanation": explanation,
            "is_mock": analysis.is_mock,
        }

        # -------------------------------------------------------------------
        # 2. Real Unit Test Execution + Code Coverage (pytest + coverage.py)
        # -------------------------------------------------------------------
        unit_test_result = self._run_unit_tests_with_coverage(workflow_id, state)
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
        # 3. Advance to EVIDENCE_GENERATION
        # -------------------------------------------------------------------
        state["current_stage"] = EVIDENCE_GENERATION
        self._record(
            workflow_id,
            "code_validation",
            tool_name="code_analyzer+pytest_cov",
            output_summary={
                "quality_score": analysis.score,
                "quality_passed": analysis.passed,
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

        # Collect relevant function names from all test cases (for coverage scoping)
        test_cases = state.get("generated_tests", [])
        relevant_functions = []
        for tc in test_cases:
            relevant_functions.extend(tc.get("responsible_functions") or [])

        workspace_path = state.get("workspace_path")

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
        1. State code_generation.files_written[0].file_path
        2. evidence_output/generated_tests/<workflow_id>/ directory
        """
        # 1. Check state for files written by CodeGeneratorAgent
        code_gen = state.get("code_generation") or {}
        files_written = code_gen.get("files_written") or []
        for fw in files_written:
            fpath = fw.get("file_path") or fw.get("relative_path")
            if fpath and os.path.isfile(fpath):
                return str(fpath)

        # 2. Scan evidence_output/generated_tests/<workflow_id>/
        evidence_test_dir = Path("evidence_output") / "generated_tests" / workflow_id
        if evidence_test_dir.is_dir():
            lang = (state.get("project") or {}).get("target_language", "python").lower()
            pattern = "*.py" if lang == "python" else f"*.{lang}"
            # Find first test file in directory
            for p in evidence_test_dir.glob(pattern):
                if p.is_file() and not p.name.startswith("conftest"):
                    return str(p.resolve())

        return None
