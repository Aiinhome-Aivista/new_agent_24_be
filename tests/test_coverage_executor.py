"""
Unit tests for the Code Coverage Executor.

Tests that:
1. The PytestCoverageExecutor correctly identifies missing test files
2. Coverage parsing handles valid JSON reports correctly
3. Source file scoping identifies correct files from function names
4. CoverageResult.to_dict() serializes correctly
"""
import os
import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.tools.code_coverage.executor import (
    PytestCoverageExecutor,
    CoverageResult,
    FileCoverageDetail,
    _parse_pytest_output,
    _parse_coverage_json,
    _identify_scoped_source_files,
    get_coverage_executor,
)


# ─────────────────────────────────────────────────────────────────────────────
# _parse_pytest_output
# ─────────────────────────────────────────────────────────────────────────────

class TestParsePytestOutput:
    def test_parses_standard_summary(self):
        output = "5 passed, 1 failed, 0 skipped in 2.34s"
        result = _parse_pytest_output(output)
        assert result["passed"] == 5
        assert result["failed"] == 1
        assert result["skipped"] == 0
        assert result["time_s"] == pytest.approx(2.34)

    def test_parses_all_passed(self):
        output = "10 passed in 0.50s"
        result = _parse_pytest_output(output)
        assert result["passed"] == 10
        assert result["failed"] == 0

    def test_parses_empty_output(self):
        result = _parse_pytest_output("")
        assert result["passed"] == 0
        assert result["failed"] == 0

    def test_parses_with_error(self):
        output = "3 passed, 2 failed, 1 error in 5.00s"
        result = _parse_pytest_output(output)
        assert result["passed"] == 3
        assert result["failed"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# _parse_coverage_json
# ─────────────────────────────────────────────────────────────────────────────

class TestParseCoverageJson:
    def test_parses_valid_json_report(self, tmp_path):
        report = {
            "totals": {
                "num_statements": 100,
                "missing_lines": 10,
                "num_branches": 50,
                "num_partial_branches": 5,
            },
            "files": {
                "/app/auth.py": {
                    "summary": {
                        "num_statements": 60,
                        "missing_lines": 5,
                        "num_branches": 30,
                        "num_partial_branches": 2,
                    },
                    "missing_lines": [10, 15, 20, 25, 30],
                }
            }
        }
        report_path = tmp_path / "coverage.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")

        result = _parse_coverage_json(str(report_path), "/app")

        assert result["line_coverage_pct"] == 90.0  # 90 / 100 = 90%
        assert result["branch_coverage_pct"] == 90.0  # 45 / 50 = 90%
        assert result["num_statements"] == 100
        assert result["num_missing"] == 10
        assert len(result["covered_files"]) == 1
        assert result["covered_files"][0].line_coverage_pct == pytest.approx(91.7, abs=0.5)

    def test_handles_missing_file(self, tmp_path):
        result = _parse_coverage_json(str(tmp_path / "nonexistent.json"), "/app")
        assert result == {}

    def test_handles_invalid_json(self, tmp_path):
        bad_path = tmp_path / "bad.json"
        bad_path.write_text("not json")
        result = _parse_coverage_json(str(bad_path), "/app")
        assert result == {}

    def test_zero_statements_returns_zero_pct(self, tmp_path):
        report = {
            "totals": {"num_statements": 0, "missing_lines": 0, "num_branches": 0, "num_partial_branches": 0},
            "files": {}
        }
        report_path = tmp_path / "coverage.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        result = _parse_coverage_json(str(report_path), "/app")
        assert result["line_coverage_pct"] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# _identify_scoped_source_files
# ─────────────────────────────────────────────────────────────────────────────

class TestIdentifyScopedSourceFiles:
    def test_returns_empty_for_missing_workspace(self):
        result = _identify_scoped_source_files("/nonexistent/path", ["auth_service.login"])
        assert result == []

    def test_finds_matching_files(self, tmp_path):
        # Create a fake workspace
        (tmp_path / "app").mkdir()
        auth = tmp_path / "app" / "auth_service.py"
        auth.write_text("# auth service")
        other = tmp_path / "app" / "ticket_controller.py"
        other.write_text("# tickets")

        scoped = _identify_scoped_source_files(
            str(tmp_path),
            ["auth_service.login", "auth_service.validate_token"]
        )
        # Should find auth_service.py
        assert any("auth_service" in f for f in scoped)

    def test_empty_functions_returns_app_dir_files(self, tmp_path):
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "main.py").write_text("# main")

        scoped = _identify_scoped_source_files(str(tmp_path), [])
        assert any("main.py" in f for f in scoped)


# ─────────────────────────────────────────────────────────────────────────────
# PytestCoverageExecutor
# ─────────────────────────────────────────────────────────────────────────────

class TestPytestCoverageExecutor:
    def test_missing_test_file_returns_error(self):
        executor = PytestCoverageExecutor()
        result = executor.run(test_file_path="/nonexistent/test_file.py")
        assert result.executed is False
        assert result.is_mock is True
        assert "not found" in (result.error_message or "")

    def test_returns_coverage_result_type(self):
        executor = PytestCoverageExecutor()
        result = executor.run(test_file_path="/nonexistent/file.py")
        assert isinstance(result, CoverageResult)

    def test_runs_real_test_and_captures_coverage(self, tmp_path):
        """
        End-to-end test: write a simple target module and a pytest test file,
        then verify that the executor captures real coverage.
        """
        # Create a simple target module
        target_dir = tmp_path / "myapp"
        target_dir.mkdir()
        (target_dir / "__init__.py").write_text("")
        target_module = target_dir / "calc.py"
        target_module.write_text(
            "def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b\n"
        )

        # Create a test file that covers `add` only
        test_file = tmp_path / "test_calc.py"
        test_file.write_text(
            "import sys\nsys.path.insert(0, r'" + str(tmp_path) + "')\n"
            "from myapp.calc import add\n\n"
            "def test_add():\n    assert add(1, 2) == 3\n"
        )

        executor = PytestCoverageExecutor(timeout_seconds=60)
        result = executor.run(
            test_file_path=str(test_file),
            workspace_path=str(tmp_path),
        )

        # The executor ran and completed
        assert result.executed is True
        assert result.is_mock is False
        assert result.error_message is None

        # pytest ran the test (check raw output for PASSED)
        assert "PASSED" in result.pytest_output or "passed" in result.pytest_output

        # Coverage was measured from actual tool (not LLM)
        assert result.line_coverage_pct > 0.0
        assert len(result.covered_files) > 0

        # calc.py specifically should appear in covered files
        calc_file = next((f for f in result.covered_files if "calc" in f.file_path), None)
        assert calc_file is not None
        # add() was tested, subtract() was not — coverage should be > 0% and < 100%
        assert calc_file.line_coverage_pct > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# CoverageResult.to_dict()
# ─────────────────────────────────────────────────────────────────────────────

class TestCoverageResultToDict:
    def test_to_dict_has_required_keys(self):
        result = CoverageResult(
            executed=True, is_mock=False, total_tests=5, passed_tests=4,
            failed_tests=1, line_coverage_pct=80.0, branch_coverage_pct=75.0
        )
        d = result.to_dict()
        assert "executed" in d
        assert "line_coverage_pct" in d
        assert "branch_coverage_pct" in d
        assert "covered_files" in d
        assert d["line_coverage_pct"] == 80.0

    def test_covered_files_serialized_as_list_of_dicts(self):
        result = CoverageResult(
            covered_files=[
                FileCoverageDetail(
                    file_path="/app/auth.py",
                    relative_path="app/auth.py",
                    line_coverage_pct=91.0,
                    branch_coverage_pct=85.0,
                    num_statements=100,
                    num_missing=9,
                )
            ]
        )
        d = result.to_dict()
        assert len(d["covered_files"]) == 1
        assert d["covered_files"][0]["line_coverage_pct"] == 91.0
        assert d["covered_files"][0]["relative_path"] == "app/auth.py"


# ─────────────────────────────────────────────────────────────────────────────
# get_coverage_executor singleton
# ─────────────────────────────────────────────────────────────────────────────

def test_get_coverage_executor_returns_singleton():
    e1 = get_coverage_executor()
    e2 = get_coverage_executor()
    assert e1 is e2
    assert isinstance(e1, PytestCoverageExecutor)
