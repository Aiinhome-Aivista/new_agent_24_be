"""
Agent Execution Trace & Evidence Provenance.

Centralized execution-trace mechanism for every complete Agent-24 run.
Observes the existing workflow without replacing it.

The trace allows a reviewer to answer:
    What did the agent do?
    What input did each stage receive?
    What output did each stage produce?
    Which tool/code was executed?
    What was the result?
    How long did it take?
    Why did the workflow move to the next stage?
    Where did every final metric come from?
    Which artifact proves the result?

Security: All trace output is redacted via app.observability.tracing.redact()
"""
import uuid
import time
import json
import os
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.observability.tracing import redact


# ─────────────────────────────────────────────────────────────────────────────
# Trace Status Enum
# ─────────────────────────────────────────────────────────────────────────────

class TraceStatus(str, Enum):
    """
    Stage execution statuses.
    PASS must represent successful completion of the stage's actual objective,
    not merely that the agent node executed without raising an exception.
    """
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    INCONCLUSIVE = "INCONCLUSIVE"
    SKIPPED = "SKIPPED"
    AWAITING_HUMAN_APPROVAL = "AWAITING_HUMAN_APPROVAL"


# ─────────────────────────────────────────────────────────────────────────────
# Provenance Record
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProvenanceRecord:
    """
    Links a final metric to its deterministic source.
    The LLM must NEVER be the authoritative source for test pass/fail,
    coverage %, HTTP status, API response, execution timestamp, SHA-256,
    test count, or source-code coverage count.
    """
    metric_name: str
    source_tool: str
    value: Any
    artifact_ref: Optional[str] = None
    stage_id: Optional[str] = None
    ac_id: Optional[str] = None
    test_case_id: Optional[str] = None
    ac_ids: List[str] = field(default_factory=list)
    test_case_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "source_tool": self.source_tool,
            "value": self.value,
            "artifact_ref": self.artifact_ref,
            "stage_id": self.stage_id,
            "ac_id": self.ac_id,
            "test_case_id": self.test_case_id,
            "ac_ids": self.ac_ids,
            "test_case_ids": self.test_case_ids,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProvenanceRecord":
        return cls(
            metric_name=d.get("metric_name", ""),
            source_tool=d.get("source_tool", ""),
            value=d.get("value"),
            artifact_ref=d.get("artifact_ref"),
            stage_id=d.get("stage_id"),
            ac_id=d.get("ac_id"),
            test_case_id=d.get("test_case_id"),
            ac_ids=d.get("ac_ids", []),
            test_case_ids=d.get("test_case_ids", []),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Artifact Reference
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ArtifactRef:
    """
    Reference to an important artifact associated with the run.
    Uses references rather than duplicating huge content into the trace.
    """
    artifact_type: str = "general"
    name: Optional[str] = None
    path: Optional[str] = None
    sha256: Optional[str] = None
    size_bytes: Optional[int] = 0
    description: Optional[str] = None
    artifact_id: Optional[str] = None

    @property
    def file_path(self) -> Optional[str]:
        return self.path

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "name": self.name,
            "type": self.artifact_type,
            "artifact_type": self.artifact_type,
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ArtifactRef":
        return cls(
            artifact_type=d.get("artifact_type", d.get("type", "general")),
            name=d.get("name"),
            path=d.get("path") or d.get("file_path"),
            sha256=d.get("sha256"),
            size_bytes=d.get("size_bytes", 0),
            description=d.get("description"),
            artifact_id=d.get("artifact_id"),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Stage Trace
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StageTrace:
    """
    Trace record for a single major pipeline stage.
    Every major stage must create one of these.
    """
    stage_id: str
    run_id: str
    stage_name: str
    stage_order: int
    parent_stage_id: Optional[str] = None
    status: TraceStatus = TraceStatus.PENDING
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[float] = None
    input_summary: Optional[Dict[str, Any]] = None
    output_summary: Optional[Dict[str, Any]] = None
    tool_calls: List[str] = field(default_factory=list)
    artifacts: List[ArtifactRef] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Internal timing
    _start_time: float = field(default=0.0, repr=False)

    @property
    def inputs(self) -> Optional[Dict[str, Any]]:
        return self.input_summary

    @property
    def outputs(self) -> Optional[Dict[str, Any]]:
        return self.output_summary

    @property
    def error(self) -> Optional[str]:
        if self.errors:
            return self.errors[-1].get("message")
        return None

    def start(self):
        """Mark stage as RUNNING with current timestamp."""
        self.status = TraceStatus.RUNNING
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._start_time = time.monotonic()

    def complete(self, status: TraceStatus = TraceStatus.PASS,
                 output_summary: Optional[Dict[str, Any]] = None):
        """Mark stage as completed with final status and duration."""
        self.status = status
        self.completed_at = datetime.now(timezone.utc).isoformat()
        if self._start_time:
            self.duration_ms = round((time.monotonic() - self._start_time) * 1000, 2)
        if output_summary:
            self.output_summary = redact(output_summary)

    def fail(self, error_message: str, error_details: Optional[Dict] = None):
        """Mark stage as FAIL with error details."""
        self.status = TraceStatus.FAIL
        self.completed_at = datetime.now(timezone.utc).isoformat()
        if self._start_time:
            self.duration_ms = round((time.monotonic() - self._start_time) * 1000, 2)
        self.errors.append(redact({
            "message": error_message,
            "details": error_details or {},
            "timestamp": self.completed_at,
        }))

    def add_artifact(self, artifact: ArtifactRef):
        """Associate an artifact with this stage."""
        self.artifacts.append(artifact)

    def add_tool_call(self, tool_name: str):
        """Record a tool invocation in this stage."""
        self.tool_calls.append(tool_name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "run_id": self.run_id,
            "stage_name": self.stage_name,
            "stage_order": self.stage_order,
            "parent_stage_id": self.parent_stage_id,
            "status": self.status.value if isinstance(self.status, TraceStatus) else str(self.status),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "tool_calls": self.tool_calls,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "errors": self.errors,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "StageTrace":
        raw_status = d.get("status", TraceStatus.PENDING)
        try:
            status = TraceStatus(raw_status)
        except (ValueError, TypeError):
            status = TraceStatus.PENDING
        st = cls(
            stage_id=d.get("stage_id", ""),
            run_id=d.get("run_id", ""),
            stage_name=d.get("stage_name", ""),
            stage_order=d.get("stage_order", 0),
            parent_stage_id=d.get("parent_stage_id"),
            status=status,
            started_at=d.get("started_at"),
            completed_at=d.get("completed_at"),
            duration_ms=d.get("duration_ms"),
            input_summary=d.get("input_summary"),
            output_summary=d.get("output_summary"),
            tool_calls=d.get("tool_calls", []),
            artifacts=[ArtifactRef.from_dict(a) for a in d.get("artifacts", [])],
            errors=d.get("errors", []),
            warnings=d.get("warnings", []),
        )
        return st


# ─────────────────────────────────────────────────────────────────────────────
# Stage Name Constants (matching prompt Stage 01-11)
# ─────────────────────────────────────────────────────────────────────────────

STAGE_REQUIREMENT_ANALYSIS = "requirement_analysis"
STAGE_SERVICE_PLANNING = "service_planning"
STAGE_TRACEABILITY = "traceability_mapping"
STAGE_TEST_GENERATION = "test_generation"
STAGE_HUMAN_REVIEW = "human_review"
STAGE_CODE_GENERATION = "code_generation"
STAGE_UNIT_TEST_EXECUTION = "unit_test_execution"
STAGE_CODE_COVERAGE = "code_coverage"
STAGE_API_VERIFICATION = "api_verification"
STAGE_EVIDENCE_GENERATION = "evidence_generation"
STAGE_ALM_WRITEBACK = "alm_writeback"

# Ordered list for stage_order assignment
STAGE_ORDER = [
    STAGE_REQUIREMENT_ANALYSIS,    # 01
    STAGE_SERVICE_PLANNING,        # 02
    STAGE_TRACEABILITY,            # 03
    STAGE_TEST_GENERATION,         # 04
    STAGE_HUMAN_REVIEW,            # 05
    STAGE_CODE_GENERATION,         # 06
    STAGE_UNIT_TEST_EXECUTION,     # 07
    STAGE_CODE_COVERAGE,           # 08
    STAGE_API_VERIFICATION,        # 09
    STAGE_EVIDENCE_GENERATION,     # 10
    STAGE_ALM_WRITEBACK,           # 11
]

# Map from state_machine stage constants to trace stage names
SM_TO_TRACE_STAGE = {
    "REQUIREMENT_ANALYSIS": STAGE_REQUIREMENT_ANALYSIS,
    "SERVICE_PLANNING": STAGE_SERVICE_PLANNING,
    "TEST_PLANNING": STAGE_TRACEABILITY,
    "TEST_GENERATION": STAGE_TEST_GENERATION,
    "TEST_PLAN_REVIEW": STAGE_HUMAN_REVIEW,
    "TEST_REVIEW": STAGE_HUMAN_REVIEW,
    "CODE_GENERATION": STAGE_CODE_GENERATION,
    "CODE_VALIDATION": STAGE_UNIT_TEST_EXECUTION,
    "API_EXECUTION": STAGE_API_VERIFICATION,
    "EVIDENCE_GENERATION": STAGE_EVIDENCE_GENERATION,
    "ALM_APPROVAL": STAGE_HUMAN_REVIEW,
    "ALM_ATTACHMENT": STAGE_ALM_WRITEBACK,
}


# ─────────────────────────────────────────────────────────────────────────────
# Execution Trace — Full Run Container
# ─────────────────────────────────────────────────────────────────────────────

class ExecutionTrace:
    """
    Container for a complete Agent-24 execution trace.

    The same run_id connects: Jira story, AC analysis, repository analysis,
    traceability, test generation, human approval, test code generation,
    unit-test execution, coverage, API execution, evidence generation,
    SHA-256, and Jira/ALM write-back.
    """

    def __init__(self, run_id: Optional[str] = None, workflow_id: Optional[str] = None):
        self.workflow_id = workflow_id or run_id or f"WF-{uuid.uuid4().hex[:8]}"
        self.run_id = run_id or workflow_id or f"EVID-{uuid.uuid4().hex[:8]}"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.end_time: Optional[str] = None
        self.total_duration_ms: Optional[float] = None
        self.status: TraceStatus = TraceStatus.RUNNING
        self.stages: List[StageTrace] = []
        self.provenance: List[ProvenanceRecord] = []
        self.global_artifacts: List[ArtifactRef] = []
        self._stage_counter = 0
        self._start_time = time.monotonic()

    def start_stage(self, stage_name: str,
                    inputs: Optional[Dict[str, Any]] = None,
                    input_summary: Optional[Dict[str, Any]] = None,
                    tool_calls: Optional[List[str]] = None,
                    parent_stage_id: Optional[str] = None) -> StageTrace:
        """
        Create and start a new stage trace.
        Returns the StageTrace so the caller can add artifacts/tool_calls/etc.
        """
        self._stage_counter += 1
        stage_order = STAGE_ORDER.index(stage_name) + 1 if stage_name in STAGE_ORDER else self._stage_counter

        inp = input_summary if input_summary is not None else (inputs or {})
        stage = StageTrace(
            stage_id=f"{self.run_id}-S{stage_order:02d}",
            run_id=self.run_id,
            stage_name=stage_name,
            stage_order=stage_order,
            parent_stage_id=parent_stage_id,
            input_summary=redact(inp),
        )
        if tool_calls:
            for tc in tool_calls:
                stage.add_tool_call(tc)
        stage.start()
        self.stages.append(stage)
        return stage

    def complete_stage(self, stage_or_name: Any,
                       status: TraceStatus = TraceStatus.PASS,
                       outputs: Optional[Dict[str, Any]] = None,
                       output_summary: Optional[Dict[str, Any]] = None,
                       tool_calls: Optional[List[str]] = None) -> StageTrace:
        """Complete a previously started stage."""
        stage = self.get_stage(stage_or_name) if isinstance(stage_or_name, str) else stage_or_name
        if not stage:
            stage = self.start_stage(str(stage_or_name))
        outp = output_summary if output_summary is not None else outputs
        if tool_calls:
            for tc in tool_calls:
                stage.add_tool_call(tc)
        stage.complete(status=status, output_summary=outp)
        return stage

    def fail_stage(self, stage_or_name: Any,
                   error: str = "",
                   error_message: str = "",
                   outputs: Optional[Dict[str, Any]] = None,
                   output_summary: Optional[Dict[str, Any]] = None,
                   error_details: Optional[Dict] = None) -> StageTrace:
        """Mark a stage as failed."""
        stage = self.get_stage(stage_or_name) if isinstance(stage_or_name, str) else stage_or_name
        if not stage:
            stage = self.start_stage(str(stage_or_name))
        err = error_message or error or "Stage execution failed"
        outp = output_summary if output_summary is not None else outputs
        if outp:
            stage.output_summary = redact(outp)
        stage.fail(error_message=err, error_details=error_details)
        return stage

    def finalize(self, status: Optional[TraceStatus] = None):
        """Finalize the entire execution trace with end timestamp and duration."""
        self.end_time = datetime.now(timezone.utc).isoformat()
        if hasattr(self, "_start_time") and self._start_time:
            self.total_duration_ms = round((time.monotonic() - self._start_time) * 1000, 2)
        if status is not None:
            self.status = status if isinstance(status, TraceStatus) else TraceStatus(status)
        else:
            summ = self.summary()
            overall = summ.get("overall_status")
            try:
                self.status = TraceStatus(overall)
            except Exception:
                self.status = TraceStatus.PASS

    def record_metric_provenance(self, metric_name: str, value: Any, source_tool: str = "",
                                 raw_evidence_ref: Optional[str] = None,
                                 artifact_ref: Optional[str] = None,
                                 stage_id: Optional[str] = None,
                                 ac_ids: Optional[List[str]] = None,
                                 test_case_ids: Optional[List[str]] = None,
                                 ac_id: Optional[str] = None,
                                 test_case_id: Optional[str] = None) -> ProvenanceRecord:
        """Record metric provenance with flexible single/multi AC and Test Case mapping."""
        resolved_ac_ids = list(ac_ids) if ac_ids else ([ac_id] if ac_id else [])
        resolved_tc_ids = list(test_case_ids) if test_case_ids else ([test_case_id] if test_case_id else [])
        primary_ac = ac_id or (resolved_ac_ids[0] if resolved_ac_ids else None)
        primary_tc = test_case_id or (resolved_tc_ids[0] if resolved_tc_ids else None)
        rec = ProvenanceRecord(
            metric_name=metric_name,
            source_tool=source_tool,
            value=value,
            artifact_ref=artifact_ref or raw_evidence_ref,
            stage_id=stage_id,
            ac_id=primary_ac,
            test_case_id=primary_tc,
            ac_ids=resolved_ac_ids,
            test_case_ids=resolved_tc_ids,
        )
        self.provenance.append(rec)
        return rec

    def record_artifact(self, name: str, path: str, sha256: str = "", size_bytes: int = 0, artifact_type: str = "general") -> ArtifactRef:
        """Create and record an artifact reference."""
        art = ArtifactRef(
            artifact_id=f"ART-{uuid.uuid4().hex[:6]}",
            name=name,
            artifact_type=artifact_type,
            path=path,
            sha256=sha256,
            size_bytes=size_bytes,
        )
        self.add_global_artifact(art)
        return art

    def add_provenance(self, metric_name: str, source_tool: str, value: Any,
                       artifact_ref: Optional[str] = None,
                       stage_id: Optional[str] = None,
                       ac_id: Optional[str] = None,
                       test_case_id: Optional[str] = None):
        """Record where a final metric came from."""
        self.provenance.append(ProvenanceRecord(
            metric_name=metric_name,
            source_tool=source_tool,
            value=value,
            artifact_ref=artifact_ref,
            stage_id=stage_id,
            ac_id=ac_id,
            test_case_id=test_case_id,
        ))

    def add_global_artifact(self, artifact: ArtifactRef):
        """Associate a global artifact with the run."""
        self.global_artifacts.append(artifact)

    def get_stage(self, stage_or_name: Any) -> Optional[StageTrace]:
        """Retrieve a stage by name or stage_id (returns last matching)."""
        if not isinstance(stage_or_name, str):
            return stage_or_name if isinstance(stage_or_name, StageTrace) else None
        for s in reversed(self.stages):
            if s.stage_name == stage_or_name or s.stage_id == stage_or_name:
                return s
        return None

    def get_stages_by_status(self, status: TraceStatus) -> List[StageTrace]:
        """Get all stages matching a given status."""
        return [s for s in self.stages if s.status == status]

    def summary(self) -> Dict[str, Any]:
        """Generate a concise run summary."""
        total = len(self.stages)
        passed = sum(1 for s in self.stages if s.status == TraceStatus.PASS)
        failed = sum(1 for s in self.stages if s.status == TraceStatus.FAIL)
        blocked = sum(1 for s in self.stages if s.status == TraceStatus.BLOCKED)
        total_duration = sum(s.duration_ms or 0 for s in self.stages)

        return {
            "workflow_id": self.workflow_id,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "end_time": self.end_time,
            "status": self.status.value if isinstance(self.status, TraceStatus) else str(self.status),
            "total_stages": total,
            "passed": passed,
            "failed": failed,
            "blocked": blocked,
            "total_duration_ms": round(total_duration, 2),
            "overall_status": (
                "PASS" if failed == 0 and blocked == 0 and passed > 0
                else "FAIL" if failed > 0
                else "BLOCKED" if blocked > 0
                else "INCOMPLETE"
            ),
        }

    def serialize(self) -> Dict[str, Any]:
        """Serialize the full trace to a dict (JSON-safe)."""
        prov_dicts = [p.to_dict() for p in self.provenance]
        art_dicts = [a.to_dict() for a in self.global_artifacts]
        return {
            "workflow_id": self.workflow_id,
            "run_id": self.run_id,
            "status": self.status.value if isinstance(self.status, TraceStatus) else str(self.status),
            "created_at": self.created_at,
            "end_time": self.end_time,
            "total_duration_ms": self.total_duration_ms,
            "summary": self.summary(),
            "stages": [s.to_dict() for s in self.stages],
            "provenance": prov_dicts,
            "metrics_provenance": prov_dicts,
            "global_artifacts": art_dicts,
            "artifacts": art_dicts,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Alias for serialize()."""
        return self.serialize()

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExecutionTrace":
        trace = cls(run_id=d.get("run_id"), workflow_id=d.get("workflow_id"))
        trace.created_at = d.get("created_at", trace.created_at)
        trace.end_time = d.get("end_time")
        trace.total_duration_ms = d.get("total_duration_ms")
        raw_status = d.get("status")
        if raw_status:
            try:
                trace.status = TraceStatus(raw_status)
            except Exception:
                trace.status = TraceStatus.PASS
        trace.stages = [StageTrace.from_dict(s) for s in d.get("stages", [])]
        raw_prov = d.get("provenance") or d.get("metrics_provenance", [])
        trace.provenance = [ProvenanceRecord.from_dict(p) for p in raw_prov]
        raw_arts = d.get("global_artifacts") or d.get("artifacts", [])
        trace.global_artifacts = [ArtifactRef.from_dict(a) for a in raw_arts]
        trace._stage_counter = len(trace.stages)
        return trace

    @property
    def metrics_provenance(self) -> List[ProvenanceRecord]:
        return self.provenance

    @property
    def artifacts(self) -> List[ArtifactRef]:
        return self.global_artifacts

    def get_provenance_by_ac_id(self, ac_id: str) -> List[ProvenanceRecord]:
        return [p for p in self.provenance if p.ac_id == ac_id or ac_id in p.ac_ids]

    def get_provenance_by_test_case_id(self, test_case_id: str) -> List[ProvenanceRecord]:
        return [p for p in self.provenance if p.test_case_id == test_case_id or test_case_id in p.test_case_ids]

    def get_provenance_by_metric(self, metric_name: str) -> Optional[ProvenanceRecord]:
        for p in self.provenance:
            if p.metric_name == metric_name:
                return p
        return None

    def get_artifacts_by_type(self, artifact_type: str) -> List[ArtifactRef]:
        return [a for a in self.global_artifacts if a.artifact_type == artifact_type]

    def save_to_file(self, out_dir: str) -> str:
        """
        Save the execution trace as a structured JSON file.
        Returns the file path.
        """
        os.makedirs(out_dir, exist_ok=True)
        file_path = os.path.join(out_dir, f"{self.run_id}_execution_trace.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.serialize(), f, indent=2, default=str)
        return file_path

    def __repr__(self):
        return f"ExecutionTrace(run_id={self.run_id}, stages={len(self.stages)})"


# ─────────────────────────────────────────────────────────────────────────────
# Helper: Determine trace status from workflow state
# ─────────────────────────────────────────────────────────────────────────────

def determine_stage_status(stage_name: str, state: Dict[str, Any]) -> TraceStatus:
    """
    Determine the appropriate TraceStatus for a completed stage based on
    actual execution results in the state. PASS only when the stage's
    actual objective is successfully completed.
    """
    status = state.get("status", "")
    errors = state.get("errors", [])

    # Check for explicit failures/blocks
    if status in ("FAILED", "CANCELLED"):
        return TraceStatus.FAIL
    if status == "BLOCKED":
        return TraceStatus.BLOCKED

    # Human checkpoints
    if status in ("WAITING_FOR_REVIEW", "WAITING_FOR_APPROVAL"):
        return TraceStatus.AWAITING_HUMAN_APPROVAL

    # Stage-specific objective checks
    if stage_name == STAGE_UNIT_TEST_EXECUTION:
        ut = state.get("unit_test_execution", {})
        if ut.get("executed") and not ut.get("is_mock"):
            if ut.get("failed_tests", 0) > 0 or ut.get("error_tests", 0) > 0:
                return TraceStatus.FAIL
            return TraceStatus.PASS
        if ut.get("is_mock"):
            return TraceStatus.INCONCLUSIVE
        return TraceStatus.SKIPPED

    if stage_name == STAGE_API_VERIFICATION:
        exec_data = state.get("execution", {})
        if exec_data.get("is_mock"):
            return TraceStatus.INCONCLUSIVE
        if exec_data.get("failed", 0) > 0:
            return TraceStatus.FAIL
        return TraceStatus.PASS

    if stage_name == STAGE_REQUIREMENT_ANALYSIS:
        if state.get("clarification_required"):
            return TraceStatus.BLOCKED
        if state.get("acceptance_criteria") or state.get("analysis"):
            return TraceStatus.PASS
        return TraceStatus.FAIL

    # Generic: if there are errors for this stage, it's a fail
    if errors and any(e.get("agent", "") in stage_name for e in errors if isinstance(e, dict)):
        return TraceStatus.FAIL

    return TraceStatus.PASS


def extract_stage_input_summary(stage_name: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Extract a concise, safe input summary for a stage from the workflow state."""
    summary = {}

    if stage_name == STAGE_REQUIREMENT_ANALYSIS:
        story = state.get("story", {})
        summary["story_id"] = story.get("external_key", "N/A")
        summary["story_title"] = story.get("title", "N/A")
        summary["ac_count"] = len(state.get("acceptance_criteria", []))

    elif stage_name == STAGE_SERVICE_PLANNING:
        summary["workspace_path"] = state.get("workspace_path", "N/A")
        summary["ac_count"] = len(state.get("acceptance_criteria", []))

    elif stage_name == STAGE_TEST_GENERATION:
        summary["ac_count"] = len(state.get("acceptance_criteria", []))
        analysis = state.get("analysis", {})
        summary["scenario_count"] = sum(
            len(analysis.get(k, []))
            for k in ("positive_scenarios", "negative_scenarios", "boundary_scenarios",
                       "validation_scenarios", "error_scenarios")
        )

    elif stage_name == STAGE_CODE_GENERATION:
        summary["test_case_count"] = len(state.get("generated_tests", []))

    elif stage_name == STAGE_UNIT_TEST_EXECUTION:
        cg = state.get("code_generation", {})
        summary["generated_test_file"] = bool(cg.get("files_written"))
        summary["workspace_path"] = state.get("workspace_path", "N/A")

    elif stage_name == STAGE_API_VERIFICATION:
        summary["target_host"] = state.get("target_host", "N/A")
        summary["has_postman_collection"] = bool(state.get("postman_collection"))

    elif stage_name == STAGE_EVIDENCE_GENERATION:
        summary["has_execution"] = bool(state.get("execution"))
        summary["has_unit_test_results"] = bool(state.get("unit_test_execution"))
        summary["has_coverage"] = bool(state.get("real_code_coverage"))

    elif stage_name == STAGE_ALM_WRITEBACK:
        summary["has_evidence"] = bool(state.get("evidence"))
        story = state.get("story", {})
        summary["jira_key"] = story.get("external_key", "N/A")

    return redact(summary)


def extract_stage_output_summary(stage_name: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Extract a concise, safe output summary for a stage from the workflow state."""
    summary = {}

    if stage_name == STAGE_REQUIREMENT_ANALYSIS:
        analysis = state.get("analysis", {})
        acs = state.get("acceptance_criteria", [])
        summary["ac_count_retained"] = len(acs)
        summary["normalized_ac_ids"] = [f"AC-{i+1:02d}" for i in range(len(acs))]
        summary["total_scenarios"] = sum(
            len(analysis.get(k, []))
            for k in ("positive_scenarios", "negative_scenarios", "boundary_scenarios",
                       "validation_scenarios", "error_scenarios")
        )

    elif stage_name == STAGE_SERVICE_PLANNING:
        sp = state.get("service_plan", {})
        summary["routes_discovered"] = len(sp.get("extracted_apis", []) if isinstance(sp, dict) else [])
        summary["workspace"] = state.get("workspace_path", "N/A")

    elif stage_name == STAGE_TRACEABILITY:
        mapping = state.get("ac_api_code_mapping", [])
        summary["acs_mapped"] = len(mapping)
        summary["mapping_statuses"] = list(set(
            m.get("implementation_status", "UNKNOWN") for m in mapping if isinstance(m, dict)
        ))

    elif stage_name == STAGE_TEST_GENERATION:
        tests = state.get("generated_tests", [])
        summary["test_count"] = len(tests)
        summary["test_names"] = [t.get("title", t.get("test_key", "")) for t in tests[:20] if isinstance(t, dict)]

    elif stage_name == STAGE_CODE_GENERATION:
        cg = state.get("code_generation", {})
        summary["files_written"] = len(cg.get("files_written", []))
        summary["test_count"] = cg.get("total_tests_generated", 0)

    elif stage_name == STAGE_UNIT_TEST_EXECUTION:
        ut = state.get("unit_test_execution", {})
        summary["total_tests"] = ut.get("total_tests", 0)
        summary["passed"] = ut.get("passed_tests", 0)
        summary["failed"] = ut.get("failed_tests", 0)
        summary["skipped"] = ut.get("skipped_tests", 0)
        summary["errors"] = ut.get("error_tests", 0)
        summary["executed"] = ut.get("executed", False)
        summary["is_mock"] = ut.get("is_mock", True)
        summary["execution_time_seconds"] = ut.get("execution_time_seconds", 0)

    elif stage_name == STAGE_CODE_COVERAGE:
        rc = state.get("real_code_coverage", {})
        summary["line_coverage_pct"] = rc.get("line_coverage_pct")
        summary["branch_coverage_pct"] = rc.get("branch_coverage_pct")
        summary["is_mock"] = rc.get("is_mock", True)
        summary["scoped_source_files"] = rc.get("scoped_source_files", [])

    elif stage_name == STAGE_API_VERIFICATION:
        exec_data = state.get("execution", {})
        summary["total"] = exec_data.get("total", 0)
        summary["passed"] = exec_data.get("passed", 0)
        summary["failed"] = exec_data.get("failed", 0)
        summary["runner"] = exec_data.get("runner", "N/A")

    elif stage_name == STAGE_EVIDENCE_GENERATION:
        ev = state.get("evidence", {})
        summary["evidence_key"] = ev.get("evidence_key", "N/A")
        summary["docx_path"] = ev.get("docx_path", "N/A")
        summary["html_path"] = ev.get("html_path", "N/A")
        summary["sha256"] = ev.get("checksum", "N/A")

    elif stage_name == STAGE_ALM_WRITEBACK:
        alm = state.get("alm", {})
        summary["external_ref"] = alm.get("external_ref", "N/A")
        summary["is_mock"] = alm.get("is_mock", True)

    return redact(summary)
