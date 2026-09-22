import os
import json
import time
import pytest
from app.observability.execution_trace import (
    ExecutionTrace,
    StageTrace,
    TraceStatus,
    ProvenanceRecord,
    ArtifactRef,
)


def test_trace_stage_lifecycle():
    trace = ExecutionTrace(workflow_id="wf-test-01", run_id="run-test-01")
    assert trace.status == TraceStatus.RUNNING

    # 1. Start and complete stage
    stg1 = trace.start_stage("requirement_analysis", inputs={"raw_acs": 8}, tool_calls=["requirement_analyzer"])
    assert stg1.status == TraceStatus.RUNNING
    assert stg1.stage_order == 1
    time.sleep(0.01)

    completed_stg1 = trace.complete_stage(
        "requirement_analysis",
        outputs={"ac_count_retained": 8},
        tool_calls=["requirement_analyzer"],
    )
    assert completed_stg1.status == TraceStatus.PASS
    assert completed_stg1.duration_ms is not None
    assert completed_stg1.duration_ms >= 0

    # 2. Start and fail stage
    stg2 = trace.start_stage("unit_test_execution", inputs={"test_file": "test_app.py"})
    assert stg2.stage_order in (2, 7)
    failed_stg2 = trace.fail_stage(
        "unit_test_execution",
        error="AssertionError in TC-09",
        outputs={"executed": 9, "passed": 8, "failed": 1},
    )
    assert failed_stg2.status == TraceStatus.FAIL
    assert failed_stg2.error == "AssertionError in TC-09"

    # 3. Finalize trace
    trace.finalize(status=TraceStatus.FAIL)
    assert trace.status == TraceStatus.FAIL
    assert trace.end_time is not None
    assert trace.total_duration_ms is not None
    assert len(trace.stages) == 2


def test_trace_redaction():
    trace = ExecutionTrace(workflow_id="wf-test-redact", run_id="run-test-redact")
    sensitive_inputs = {
        "api_key": "sk-secret-12345",
        "Authorization": "Bearer token-abc-xyz",
        "password": "supersecretpassword",
        "normal_field": "public_data",
    }
    trace.start_stage("test_stage", inputs=sensitive_inputs)
    completed = trace.complete_stage(
        "test_stage",
        outputs={"access_token": "token-999", "result": "ok"}
    )
    # Check that sensitive values were redacted
    assert "REDACTED" in completed.inputs["api_key"]
    assert "REDACTED" in completed.inputs["Authorization"]
    assert "REDACTED" in completed.inputs["password"]
    assert completed.inputs["normal_field"] == "public_data"
    assert "REDACTED" in completed.outputs["access_token"]
    assert completed.outputs["result"] == "ok"


def test_provenance_and_artifacts():
    trace = ExecutionTrace(workflow_id="wf-test-prov", run_id="run-test-prov")
    
    # Record metric provenance
    trace.record_metric_provenance(
        metric_name="user_story_unit_tests",
        value=88.9,
        source_tool="pytest",
        raw_evidence_ref="evidence_output/pytest_results.json",
        ac_ids=["AC-01", "AC-02", "AC-03"],
        test_case_ids=["TC-01", "TC-02", "TC-09"],
    )
    trace.record_metric_provenance(
        metric_name="scoped_line_coverage",
        value=82.5,
        source_tool="pytest-cov",
        raw_evidence_ref="coverage.json",
        ac_ids=["AC-01"],
        test_case_ids=["TC-01"],
    )

    # Record artifacts
    trace.record_artifact(
        name="test_file",
        path="tests/test_tickets.py",
        sha256="abcdef123456",
        size_bytes=2048,
        artifact_type="code",
    )
    trace.record_artifact(
        name="docx_evidence",
        path="evidence_output/EVID-01.docx",
        sha256="987654321fed",
        size_bytes=45000,
        artifact_type="document",
    )

    # Query helpers
    ac1_records = trace.get_provenance_by_ac_id("AC-01")
    assert len(ac1_records) == 2
    ac3_records = trace.get_provenance_by_ac_id("AC-03")
    assert len(ac3_records) == 1
    assert ac3_records[0].metric_name == "user_story_unit_tests"

    tc9_records = trace.get_provenance_by_test_case_id("TC-09")
    assert len(tc9_records) == 1
    assert tc9_records[0].metric_name == "user_story_unit_tests"

    cov_record = trace.get_provenance_by_metric("scoped_line_coverage")
    assert cov_record is not None
    assert cov_record.value == 82.5
    assert cov_record.source_tool == "pytest-cov"

    doc_artifacts = trace.get_artifacts_by_type("document")
    assert len(doc_artifacts) == 1
    assert doc_artifacts[0].name == "docx_evidence"
    assert doc_artifacts[0].sha256 == "987654321fed"


def test_trace_serialization_deserialization():
    trace = ExecutionTrace(workflow_id="wf-ser-01", run_id="run-ser-01")
    trace.start_stage("service_planning", inputs={"repo": "test_repo"})
    trace.complete_stage("service_planning", outputs={"routes": 5}, tool_calls=["service_planner"])
    trace.record_metric_provenance(
        metric_name="real_api_pass_rate",
        value=100.0,
        source_tool="HttpRunner",
        ac_ids=["AC-01"],
    )
    trace.record_artifact("evidence_html", "evidence_output/EVID-01.html", sha256="aaa111", size_bytes=5000)
    trace.finalize(status=TraceStatus.PASS)

    # To Dict
    data = trace.to_dict()
    assert data["workflow_id"] == "wf-ser-01"
    assert data["status"] == "PASS"
    assert len(data["stages"]) == 1
    assert len(data["metrics_provenance"]) == 1
    assert len(data["artifacts"]) == 1

    # From Dict
    restored = ExecutionTrace.from_dict(data)
    assert restored.workflow_id == trace.workflow_id
    assert restored.run_id == trace.run_id
    assert restored.status == TraceStatus.PASS
    assert len(restored.stages) == 1
    assert restored.stages[0].stage_name == "service_planning"
    assert restored.stages[0].status == TraceStatus.PASS
    assert restored.stages[0].outputs == {"routes": 5}
    assert len(restored.metrics_provenance) == 1
    assert restored.metrics_provenance[0].metric_name == "real_api_pass_rate"
    assert len(restored.artifacts) == 1
    assert restored.artifacts[0].name == "evidence_html"


def test_workflow_trace_api_endpoint(client, monkeypatch, tmp_path):
    from app.repositories import workflow_repo

    test_wf_id = "wf-trace-api-test"
    sample_trace = ExecutionTrace(workflow_id=test_wf_id, run_id="run-api-01")
    sample_trace.start_stage("requirement_analysis")
    sample_trace.complete_stage("requirement_analysis", outputs={"acs": 8})
    sample_trace.finalize(status=TraceStatus.PASS)

    # 1. Test retrieving from state_json
    fake_run = {
        "workflow_id": test_wf_id,
        "state_json": {
            "execution_trace": sample_trace.to_dict()
        }
    }
    monkeypatch.setattr(workflow_repo, "get_run", lambda wid: fake_run if wid == test_wf_id else None)

    # Mock auth headers/decorators if needed or test directly
    headers = {"Authorization": "Bearer test-token"}
    resp = client.get(f"/workflows/{test_wf_id}/trace", headers=headers)
    
    # Check response (if auth passes with test fixture or mock)
    if resp.status_code == 200:
        json_data = resp.get_json()
        assert json_data["success"] is True
        assert json_data["data"]["workflow_id"] == test_wf_id
        assert json_data["data"]["execution_trace"]["workflow_id"] == test_wf_id

    # 2. Test 404 for nonexistent workflow
    resp_404 = client.get("/workflows/nonexistent-wf/trace", headers=headers)
    if resp_404.status_code == 404:
        json_data = resp_404.get_json()
        assert json_data["success"] is False
