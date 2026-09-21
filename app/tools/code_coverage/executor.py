"""
Real Code Coverage Executor.

Runs pytest + coverage.py (via pytest-cov) against generated unit test files
and the target source code from the user's Git repository. Returns actual
line coverage, branch coverage, and per-file breakdown.

Architecture:
    LLM -> Generated unit test file (on disk)
         -> pytest --cov=<source_dir> --cov-branch --cov-report=json
         -> coverage.py JSON report
         -> Agent parses report
         -> Returns CoverageResult (never fabricated)

Constraints:
- No Docker or external execution environment.
- Uses the existing Python/venv runtime only.
- Coverage is SCOPED to AC/API-relevant source files, not the whole backend.
- Temporary test infrastructure is cleaned up after execution.
"""

import os
import sys
import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any


@dataclass
class FileCoverageDetail:
    """Coverage details for a single source file."""
    file_path: str
    relative_path: str
    line_coverage_pct: float
    branch_coverage_pct: float
    num_statements: int
    num_missing: int
    missing_lines: List[int] = field(default_factory=list)
    num_branches: int = 0
    num_partial_branches: int = 0


@dataclass
class CoverageResult:
    """
    Real code coverage result from pytest-cov execution.
    All percentages come from the actual coverage tool — never from the LLM.
    """
    # Execution outcome
    executed: bool = False
    is_mock: bool = False
    error_message: Optional[str] = None

    # Test execution results (from pytest stdout)
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    skipped_tests: int = 0
    error_tests: int = 0
    execution_time_seconds: float = 0.0
    pytest_output: str = ""

    # Real code coverage (from coverage.py JSON report)
    line_coverage_pct: float = 0.0
    branch_coverage_pct: float = 0.0
    num_statements: int = 0
    num_missing: int = 0
    num_branches: int = 0
    num_partial_branches: int = 0

    # Per-file breakdown
    covered_files: List[FileCoverageDetail] = field(default_factory=list)
    uncovered_files: List[str] = field(default_factory=list)

    # Scope info
    scoped_source_files: List[str] = field(default_factory=list)
    coverage_report_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "executed": self.executed,
            "is_mock": self.is_mock,
            "error_message": self.error_message,
            "total_tests": self.total_tests,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests,
            "skipped_tests": self.skipped_tests,
            "error_tests": self.error_tests,
            "execution_time_seconds": self.execution_time_seconds,
            "pytest_output": self.pytest_output,
            "line_coverage_pct": self.line_coverage_pct,
            "branch_coverage_pct": self.branch_coverage_pct,
            "num_statements": self.num_statements,
            "num_missing": self.num_missing,
            "num_branches": self.num_branches,
            "num_partial_branches": self.num_partial_branches,
            "covered_files": [
                {
                    "file_path": f.file_path,
                    "relative_path": f.relative_path,
                    "line_coverage_pct": f.line_coverage_pct,
                    "branch_coverage_pct": f.branch_coverage_pct,
                    "num_statements": f.num_statements,
                    "num_missing": f.num_missing,
                    "missing_lines": f.missing_lines,
                }
                for f in self.covered_files
            ],
            "uncovered_files": self.uncovered_files,
            "scoped_source_files": self.scoped_source_files,
        }


def _parse_pytest_output(output: str) -> Dict[str, int]:
    """
    Parse pytest summary line like:
      '5 passed, 1 failed, 0 skipped in 2.34s'
    Returns dict with total, passed, failed, skipped, errors, time_s.
    """
    import re
    result = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0, "time_s": 0.0}
    # Match the summary line
    m = re.search(
        r'(?:(\d+) passed)?[,\s]*(?:(\d+) failed)?[,\s]*(?:(\d+) skipped)?[,\s]*(?:(\d+) error)?.*?in ([\d.]+)s',
        output
    )
    if m:
        result["passed"] = int(m.group(1) or 0)
        result["failed"] = int(m.group(2) or 0)
        result["skipped"] = int(m.group(3) or 0)
        result["errors"] = int(m.group(4) or 0)
        result["time_s"] = float(m.group(5) or 0)
    return result


def _parse_coverage_json(report_path: str, source_root: str) -> Dict[str, Any]:
    """
    Parse coverage.py JSON report to extract:
    - Total line coverage %
    - Total branch coverage %
    - Per-file breakdown
    """
    if not os.path.isfile(report_path):
        return {}

    try:
        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[CoverageExecutor] Could not parse coverage JSON: {e}")
        return {}

    totals = data.get("totals", {})
    files_data = data.get("files", {})

    num_statements = totals.get("num_statements", 0)
    num_missing = totals.get("missing_lines", 0)
    covered_lines = num_statements - num_missing
    line_pct = round((covered_lines / num_statements * 100) if num_statements > 0 else 0.0, 1)

    num_branches = totals.get("num_branches", 0)
    num_partial = totals.get("num_partial_branches", 0)
    covered_branches = num_branches - num_partial
    branch_pct = round((covered_branches / num_branches * 100) if num_branches > 0 else 0.0, 1)

    covered_files = []
    uncovered_files = []

    for fpath, fdata in files_data.items():
        summary = fdata.get("summary", {})
        f_statements = summary.get("num_statements", 0)
        f_missing = summary.get("missing_lines", 0)
        f_covered = f_statements - f_missing
        f_line_pct = round((f_covered / f_statements * 100) if f_statements > 0 else 0.0, 1)

        f_branches = summary.get("num_branches", 0)
        f_partial = summary.get("num_partial_branches", 0)
        f_covered_b = f_branches - f_partial
        f_branch_pct = round((f_covered_b / f_branches * 100) if f_branches > 0 else 0.0, 1)

        missing_lines = fdata.get("missing_lines", [])

        try:
            rel_path = os.path.relpath(fpath, source_root)
        except Exception:
            rel_path = fpath

        detail = FileCoverageDetail(
            file_path=fpath,
            relative_path=rel_path,
            line_coverage_pct=f_line_pct,
            branch_coverage_pct=f_branch_pct,
            num_statements=f_statements,
            num_missing=f_missing,
            missing_lines=missing_lines,
            num_branches=f_branches,
            num_partial_branches=f_partial,
        )
        covered_files.append(detail)

        if f_line_pct == 0.0 and f_statements > 0:
            uncovered_files.append(rel_path)

    return {
        "line_coverage_pct": line_pct,
        "branch_coverage_pct": branch_pct,
        "num_statements": num_statements,
        "num_missing": num_missing,
        "num_branches": num_branches,
        "num_partial_branches": num_partial,
        "covered_files": covered_files,
        "uncovered_files": uncovered_files,
    }


def _identify_scoped_source_files(
    workspace_path: str,
    relevant_functions: List[str],
) -> List[str]:
    """
    Given a workspace path and a list of relevant function/class names from test cases,
    identify the source files that should be included in coverage measurement.

    This implements AC/API-scoped coverage — we only measure coverage for source
    files that are relevant to the tested acceptance criteria, not the entire backend.

    Returns a list of absolute source file paths.
    """
    if not workspace_path or not os.path.isdir(workspace_path):
        return []

    scoped = set()

    # Normalize function names to extract module path hints
    for func_ref in (relevant_functions or []):
        # e.g. "auth_controller.login" -> look for auth_controller.py
        parts = str(func_ref).split(".")
        if len(parts) >= 2:
            module_hint = parts[0].lower().replace("-", "_")
        else:
            module_hint = parts[0].lower().replace("-", "_") if parts else ""

        if not module_hint:
            continue

        # Search workspace for matching .py files
        for root, dirs, files in os.walk(workspace_path):
            # Skip venv, __pycache__, .git, migrations, tests
            dirs[:] = [
                d for d in dirs
                if d not in ("venv", ".venv", "__pycache__", ".git", "migrations", "node_modules", "tests", "test")
            ]
            for fname in files:
                if fname.endswith(".py") and module_hint in fname.lower():
                    scoped.add(os.path.join(root, fname))

    # If we couldn't identify specific files, include the whole app/ directory
    if not scoped:
        app_dir = os.path.join(workspace_path, "app")
        if os.path.isdir(app_dir):
            for root, dirs, files in os.walk(app_dir):
                dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
                for fname in files:
                    if fname.endswith(".py"):
                        scoped.add(os.path.join(root, fname))

    return sorted(scoped)


class PytestCoverageExecutor:
    """
    Executes generated unit tests using pytest + coverage.py.

    The generated test file is run in a subprocess using the current Python
    executable (same venv). Coverage is measured against AC-scoped source files.

    NEVER fabricates coverage numbers. All results come from the actual tool.
    """

    def __init__(self, timeout_seconds: int = 120):
        self.timeout_seconds = timeout_seconds
        # Use the same Python that's running this application
        self.python_exe = sys.executable

    def run(
        self,
        test_file_path: str,
        workspace_path: Optional[str] = None,
        relevant_functions: Optional[List[str]] = None,
        conftest_path: Optional[str] = None,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> CoverageResult:
        """
        Execute the generated test file with pytest + coverage.py.

        Args:
            test_file_path: Absolute path to the generated test file (.py)
            workspace_path: Root of the user's cloned Git repository
            relevant_functions: List of function/class names from test cases
                                 used to scope coverage measurement
            conftest_path: Optional path to conftest.py to copy into temp dir
            extra_env: Additional environment variables for subprocess

        Returns:
            CoverageResult with real execution results and coverage metrics
        """
        result = CoverageResult()

        if not test_file_path or not os.path.isfile(test_file_path):
            result.error_message = f"Test file not found: {test_file_path}"
            result.is_mock = True
            return result

        # Validate pytest-cov is available
        try:
            subprocess.run(
                [self.python_exe, "-m", "pytest", "--version"],
                capture_output=True, timeout=10
            )
        except Exception as e:
            result.error_message = f"pytest not available: {e}"
            result.is_mock = True
            return result

        # Create a temporary working directory for test execution
        tmp_dir = tempfile.mkdtemp(prefix="agent24_cov_")
        coverage_json_path = os.path.join(tmp_dir, "coverage.json")

        try:
            # Determine the source directory to measure coverage on
            source_dir = workspace_path or os.path.dirname(test_file_path)
            scoped_files = _identify_scoped_source_files(
                workspace_path or "", relevant_functions or []
            )
            result.scoped_source_files = scoped_files

            # Copy test file to temp dir so it runs in isolation
            test_filename = os.path.basename(test_file_path)
            tmp_test_file = os.path.join(tmp_dir, test_filename)
            shutil.copy2(test_file_path, tmp_test_file)

            # Copy conftest.py if available
            test_dir = os.path.dirname(test_file_path)
            conftest_src = conftest_path or os.path.join(test_dir, "conftest.py")
            if os.path.isfile(conftest_src):
                shutil.copy2(conftest_src, os.path.join(tmp_dir, "conftest.py"))

            # Build pytest command with coverage
            cmd = [
                self.python_exe, "-m", "pytest",
                tmp_test_file,
                "--tb=short",
                "-v",
                "--no-header",
                f"--cov={source_dir}",
                "--cov-branch",
                "--cov-report=json:" + coverage_json_path,
                "--cov-report=term-missing",
                "-p", "no:cacheprovider",
            ]

            # If we have scoped files, use --cov-include to limit scope
            if scoped_files:
                # Build include patterns from scoped file list
                for sf in scoped_files[:20]:  # limit to 20 most relevant files
                    cmd.append(f"--cov={sf}")

            # Set up subprocess environment — inherit current env + additions
            env = os.environ.copy()
            env["PYTHONPATH"] = (workspace_path or "") + os.pathsep + env.get("PYTHONPATH", "")
            if extra_env:
                env.update(extra_env)

            print(f"[CoverageExecutor] Running pytest + coverage for: {test_filename}")
            print(f"[CoverageExecutor] Temp dir: {tmp_dir}")
            print(f"[CoverageExecutor] Source dir: {source_dir}")

            start_ts = time.time()
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=env,
                cwd=workspace_path or tmp_dir,
            )
            elapsed = time.time() - start_ts

            combined_output = (proc.stdout or "") + "\n" + (proc.stderr or "")
            result.pytest_output = combined_output.strip()
            result.execution_time_seconds = round(elapsed, 2)

            print(f"[CoverageExecutor] pytest exit code: {proc.returncode}")
            print(f"[CoverageExecutor] Output tail:\n{combined_output[-800:]}")

            # Parse pytest summary
            summary = _parse_pytest_output(combined_output)
            result.passed_tests = summary["passed"]
            result.failed_tests = summary["failed"]
            result.skipped_tests = summary["skipped"]
            result.error_tests = summary["errors"]
            result.total_tests = result.passed_tests + result.failed_tests + result.skipped_tests + result.error_tests
            result.executed = True

            # Parse coverage JSON report
            if os.path.isfile(coverage_json_path):
                cov_data = _parse_coverage_json(coverage_json_path, source_dir)
                result.line_coverage_pct = cov_data.get("line_coverage_pct", 0.0)
                result.branch_coverage_pct = cov_data.get("branch_coverage_pct", 0.0)
                result.num_statements = cov_data.get("num_statements", 0)
                result.num_missing = cov_data.get("num_missing", 0)
                result.num_branches = cov_data.get("num_branches", 0)
                result.num_partial_branches = cov_data.get("num_partial_branches", 0)
                result.covered_files = cov_data.get("covered_files", [])
                result.uncovered_files = cov_data.get("uncovered_files", [])
                result.coverage_report_path = coverage_json_path
                print(f"[CoverageExecutor] Line coverage: {result.line_coverage_pct}% | Branch: {result.branch_coverage_pct}%")
            else:
                # Coverage report not generated — tests may have errored before coverage ran
                result.line_coverage_pct = 0.0
                result.branch_coverage_pct = 0.0
                if proc.returncode != 0 and not result.error_message:
                    result.error_message = f"pytest exited with code {proc.returncode}. No coverage report generated."
                    print(f"[CoverageExecutor] WARNING: No coverage.json found. Tests may have import errors.")

        except subprocess.TimeoutExpired:
            result.error_message = f"Test execution timed out after {self.timeout_seconds}s"
            result.executed = True
            print(f"[CoverageExecutor] TIMEOUT: {result.error_message}")
        except Exception as e:
            result.error_message = f"Coverage execution error: {e}"
            result.executed = False
            print(f"[CoverageExecutor] ERROR: {e}")
        finally:
            # Clean up temporary directory
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

        return result


# Singleton-style factory
_executor_instance: Optional[PytestCoverageExecutor] = None


def get_coverage_executor(timeout_seconds: int = 120) -> PytestCoverageExecutor:
    """Return the shared PytestCoverageExecutor instance."""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = PytestCoverageExecutor(timeout_seconds=timeout_seconds)
    return _executor_instance
