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
import glob
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
    covered_branches: int = 0
    covered_lines: int = 0


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


def _parse_pytest_output(output: str) -> Dict[str, Any]:
    """
    Parse pytest summary line like:
      '5 passed, 1 failed, 0 skipped in 2.34s'
      '22 passed in 0.52s'
      '8 passed, 1 warning in 0.42s'
    Returns dict with total, passed, failed, skipped, errors, time_s.
    """
    import re
    result = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0, "time_s": 0.0}
    if not output:
        return result

    # Strip ANSI escape sequences
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    clean = ansi_escape.sub('', output)

    passed_m = re.search(r'(\d+)\s+passed', clean)
    if passed_m:
        result["passed"] = int(passed_m.group(1))

    failed_m = re.search(r'(\d+)\s+failed', clean)
    if failed_m:
        result["failed"] = int(failed_m.group(1))

    skipped_m = re.search(r'(\d+)\s+skipped', clean)
    if skipped_m:
        result["skipped"] = int(skipped_m.group(1))

    error_m = re.search(r'(\d+)\s+error', clean)
    if error_m:
        result["errors"] = int(error_m.group(1))

    time_m = re.search(r'in\s+([\d.]+)\s*s', clean)
    if time_m:
        result["time_s"] = float(time_m.group(1))

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
    covered_lines = totals.get("covered_lines", num_statements - num_missing)
    line_pct = round((covered_lines / num_statements * 100) if num_statements > 0 else 0.0, 2)

    num_branches = totals.get("num_branches", 0)
    num_partial = totals.get("num_partial_branches", 0)
    covered_branches = totals.get("covered_branches", num_branches - num_partial)
    branch_pct = round((covered_branches / num_branches * 100) if num_branches > 0 else 0.0, 2)

    covered_files = []
    uncovered_files = []

    for fpath, fdata in files_data.items():
        summary = fdata.get("summary", {})
        f_statements = summary.get("num_statements", 0)
        f_missing = summary.get("missing_lines", 0)
        f_covered = summary.get("covered_lines", f_statements - f_missing)
        f_line_pct = round((f_covered / f_statements * 100) if f_statements > 0 else 0.0, 2)

        f_branches = summary.get("num_branches", 0)
        f_partial = summary.get("num_partial_branches", 0)
        f_covered_b = summary.get("covered_branches", f_branches - f_partial)
        f_branch_pct = round((f_covered_b / f_branches * 100) if f_branches > 0 else 0.0, 2)

        missing_lines = fdata.get("missing_lines", [])

        # Determine relative path and absolute path
        if os.path.isabs(fpath):
            abs_fpath = fpath
            try:
                rel_path = os.path.relpath(fpath, source_root)
            except Exception:
                rel_path = fpath
        else:
            rel_path = fpath
            abs_fpath = os.path.abspath(os.path.join(source_root, fpath))

        detail = FileCoverageDetail(
            file_path=abs_fpath,
            relative_path=rel_path,
            line_coverage_pct=f_line_pct,
            branch_coverage_pct=f_branch_pct,
            num_statements=f_statements,
            num_missing=f_missing,
            missing_lines=missing_lines,
            num_branches=f_branches,
            num_partial_branches=f_partial,
            covered_branches=f_covered_b,
            covered_lines=f_covered,
        )
        covered_files.append(detail)

    # Filter for application source files (excluding test suites and conftest)
    app_files = [
        f for f in covered_files
        if not any(x in f.file_path.replace("\\", "/").lower() for x in ("/tests/", "tests/", "test_", "conftest.py"))
    ]

    if app_files:
        num_statements = sum(f.num_statements for f in app_files)
        num_missing = sum(f.num_missing for f in app_files)
        covered_lines = sum(f.covered_lines for f in app_files)
        line_pct = round((covered_lines / num_statements * 100) if num_statements > 0 else 0.0, 2)

        num_branches = sum(f.num_branches for f in app_files)
        num_partial = sum(f.num_partial_branches for f in app_files)
        covered_branches = sum(f.covered_branches for f in app_files)
        branch_pct = round((covered_branches / num_branches * 100) if num_branches > 0 else 0.0, 2)

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

    # Normalize function names or direct file paths to extract module path hints
    for func_ref in (relevant_functions or []):
        ref_str = str(func_ref).strip()
        if ref_str.endswith(".py"):
            norm_ref = ref_str.replace("\\", "/").lower()
            if any(skip in norm_ref for skip in ["venv", ".venv", "site-packages", "test", "tests"]):
                continue
            direct_path = os.path.join(workspace_path, ref_str)
            if os.path.isfile(direct_path):
                scoped.add(direct_path)
                continue

        # e.g. "auth_controller.login" -> look for auth_controller.py
        parts = ref_str.split(".")
        if len(parts) >= 2:
            module_hint = parts[0].lower().replace("-", "_")
        else:
            module_hint = parts[0].lower().replace("-", "_") if parts else ""

        if not module_hint or module_hint in ("venv", "lib", "site_packages", "test", "tests"):
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

    # Strip any stray venv/test paths that may have entered
    scoped = {
        p for p in scoped
        if not any(skip in p.replace("\\", "/").lower() for skip in ["/venv/", "/.venv/", "/site-packages/", "/tests/", "/test/"])
    }

    # If we couldn't identify specific files, include the whole app/ directory or root python files
    if not scoped:
        app_dir = os.path.join(workspace_path, "app")
        if os.path.isdir(app_dir):
            for root, dirs, files in os.walk(app_dir):
                dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
                for fname in files:
                    if fname.endswith(".py"):
                        scoped.add(os.path.join(root, fname))
        else:
            try:
                for item in os.listdir(workspace_path):
                    fpath = os.path.join(workspace_path, item)
                    if os.path.isfile(fpath) and item.endswith(".py") and not item.startswith("test_") and item != "conftest.py":
                        scoped.add(fpath)
            except Exception:
                pass

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
                capture_output=True, timeout=30
            )
        except Exception as e:
            result.error_message = f"pytest not available: {e}"
            result.is_mock = True
            return result

        # Determine backend root for isolated temporary runs within Agent-24
        backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        base_tmp = os.path.join(backend_root, "tmp", "coverage_runs")
        os.makedirs(base_tmp, exist_ok=True)

        # Create a dedicated temporary working directory inside Agent-24 backend
        tmp_dir = tempfile.mkdtemp(prefix="agent24_cov_", dir=base_tmp)
        coverage_json_path = os.path.join(tmp_dir, "coverage.json")
        coverage_db_path = os.path.join(tmp_dir, ".coverage")
        pytest_cache_dir = os.path.join(tmp_dir, ".pytest_cache")

        source_dir = None
        try:
            # Resolve workspace path and test file to absolute paths
            abs_workspace = os.path.abspath(workspace_path) if workspace_path and os.path.isdir(workspace_path) else None
            abs_test_file = os.path.abspath(test_file_path)

            # Determine the source directory to measure coverage on
            source_dir = abs_workspace or os.path.dirname(abs_test_file)
            scoped_files = _identify_scoped_source_files(
                source_dir, relevant_functions or []
            )
            result.scoped_source_files = scoped_files

            # Determine test file to execute:
            # If the test file is inside source_dir (workspace), run it directly so fixtures and imports resolve naturally
            test_filename = os.path.basename(abs_test_file)
            test_to_run = abs_test_file
            is_in_source = False
            try:
                is_in_source = os.path.commonpath([abs_test_file, source_dir]) == source_dir
            except Exception:
                pass

            if not is_in_source:
                # Copy test file to temp dir so it runs in isolation
                tmp_test_file = os.path.join(tmp_dir, test_filename)
                shutil.copy2(abs_test_file, tmp_test_file)
                test_to_run = tmp_test_file

                # Copy conftest.py if available
                test_dir = os.path.dirname(abs_test_file)
                conftest_src = conftest_path or os.path.join(test_dir, "conftest.py")
                if not os.path.isfile(conftest_src) and abs_workspace:
                    ws_conftest = os.path.join(abs_workspace, "tests", "conftest.py")
                    if os.path.isfile(ws_conftest):
                        conftest_src = ws_conftest

                if os.path.isfile(conftest_src):
                    shutil.copy2(conftest_src, os.path.join(tmp_dir, "conftest.py"))

            # Build scoped coverage targets (clean module names / relative packages)
            cov_modules = set()
            for sf in scoped_files:
                try:
                    rel_p = os.path.relpath(sf, source_dir)
                    mod = os.path.splitext(rel_p)[0].replace("\\", ".").replace("/", ".")
                    if mod:
                        cov_modules.add(mod)
                except Exception:
                    pass

            if not cov_modules:
                if os.path.isfile(os.path.join(source_dir, "app.py")) or os.path.isdir(os.path.join(source_dir, "app")):
                    cov_modules.add("app")
                else:
                    cov_modules.add(".")

            # Build pytest command with coverage
            cmd = [
                self.python_exe, "-m", "pytest",
                test_to_run,
                "--tb=short",
                "-v",
                "--no-header",
            ]
            for m in sorted(cov_modules):
                cmd.append(f"--cov={m}")

            cmd.extend([
                "--cov-branch",
                f"--cov-report=json:{coverage_json_path}",
                "--cov-report=term-missing",
                "-o", f"cache_dir={pytest_cache_dir}",
                "-p", "no:cacheprovider",
            ])

            # Set up subprocess environment:
            # 1. Put source_dir at the front of PYTHONPATH so target imports resolve first
            # 2. Exclude any Agent-24 backend directories so target app module is not shadowed!
            # 3. Direct COVERAGE_FILE inside tmp_dir in Agent-24 so target codebase is NEVER polluted!
            env = os.environ.copy()
            clean_paths = [source_dir]
            for p in env.get("PYTHONPATH", "").split(os.pathsep):
                p_norm = os.path.normpath(p).lower()
                if p and "new_agent_24_be" not in p_norm and p_norm != os.path.normpath(source_dir).lower():
                    clean_paths.append(p)
            env["PYTHONPATH"] = os.pathsep.join(clean_paths)
            env["COVERAGE_FILE"] = coverage_db_path
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
                cwd=source_dir,
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
            # 1. Clean up temporary directory inside Agent-24 backend
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

            # 2. Safety sweep: Ensure target source codebase is completely pristine
            # and free of any accidental .coverage or .pytest_cache files
            try:
                if source_dir and os.path.isdir(source_dir):
                    for stray in [".coverage", ".pytest_cache"]:
                        stray_path = os.path.join(source_dir, stray)
                        if os.path.isfile(stray_path):
                            os.remove(stray_path)
                        elif os.path.isdir(stray_path):
                            shutil.rmtree(stray_path, ignore_errors=True)
                    for f in glob.glob(os.path.join(source_dir, ".coverage*")):
                        try:
                            os.remove(f)
                        except Exception:
                            pass
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
