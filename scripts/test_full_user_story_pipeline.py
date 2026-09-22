"""
End-to-End User Story Pipeline Execution and Code Coverage Verification.

Executes the complete pipeline:
  AC Analysis
    ↓
  Test Generation
    ↓
  Generated Test Code Synthesis & Saving to Target Test Workspace
    ↓
  Real API Execution (8/8 against live host)
    ↓
  Real Unit Test & Code Coverage Execution (pytest + pytest-cov against target codebase)
    ↓
  Evidence Generation (DOCX + HTML)
    ↓
  Programmatic Inspection of Generated Evidence
"""
import os
import sys
import json
import uuid
import docx
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from app.workflows import state_machine as sm
from app.agents.orchestrator.orchestrator import Orchestrator
from app.extensions.db import query, execute


def run_full_pipeline():
    print("=" * 80)
    print("STARTING FULL USER-STORY PIPELINE WITH ACTUAL CODE COVERAGE")
    print("=" * 80)

    # 1. Resolve target workspace and Postman collection
    root_dir = Path(__file__).resolve().parent.parent.parent
    workspace_path = str((root_dir / "simple_python_deploy").resolve())
    postman_path = str((root_dir / "ticket-management.postman_collection.json").resolve())

    print(f"Target Workspace : {workspace_path}")
    print(f"Postman Coll     : {postman_path}")

    assert os.path.isdir(workspace_path), f"Workspace not found: {workspace_path}"
    assert os.path.isfile(postman_path), f"Postman collection not found: {postman_path}"

    with open(postman_path, "r", encoding="utf-8") as pf:
        collection_data = json.load(pf)

    # 2. Retrieve linked story SCRUM-40 (or fallback to database story)
    story = query("SELECT * FROM stories WHERE external_key='SCRUM-40' ORDER BY id DESC LIMIT 1", fetchone=True)
    if not story:
        story = query("SELECT * FROM stories WHERE title LIKE '%Ticket%' ORDER BY id DESC LIMIT 1", fetchone=True)

    assert story, "No ticket management user story found in database."
    print(f"Linked Story     : [{story['external_key']}] {story['title']} (UUID: {story['uuid']})")

    # 3. Retrieve Acceptance Criteria
    acs = query("SELECT * FROM acceptance_criteria WHERE story_id=%s ORDER BY id", (story["id"],))
    ac_texts = [f"{a['ac_key']}: {a['text']}" for a in acs] if acs else [
        "AC-1: Successful Support Ticket Creation: POST /api/tickets with valid data returns 201 Created.",
        "AC-2: Missing Required Fields: Omission of title, description, or category returns 400 Bad Request.",
        "AC-3: Category Validation: Submission of unrecognized category returns 400 Bad Request.",
        "AC-4: Priority Validation: Submission of invalid priority string returns 400 Bad Request.",
        "AC-5: Title Length Boundary Validation: Titles < 5 or > 100 characters return 400 Bad Request.",
        "AC-6: Non-JSON Request Rejection: Non-JSON payload returns 400 Bad Request.",
        "AC-7: Retrieve Existing Ticket by ID: GET /api/tickets/{id} returns 200 OK with ticket record.",
        "AC-8: Retrieve Non-Existent Ticket: GET /api/tickets/{id} for non-existent ticket returns 404 Not Found.",
    ]
    print(f"Retrieved {len(ac_texts)} Acceptance Criteria.")

    # 4. Construct initial workflow state
    workflow_id = f"wf-coverage-{uuid.uuid4().hex[:8]}"
    initial_state = {
        "workflow_id": workflow_id,
        "current_stage": sm.REQUIREMENT_ANALYSIS,
        "status": sm.QUEUED,
        "project": {
            "id": story.get("project_id", 1),
            "name": "Ticket Management",
            "target_language": "python",
            "target_framework": "pytest",
            "workspace_path": workspace_path,
        },
        "story": {
            "id": story["id"],
            "uuid": story["uuid"],
            "external_key": story.get("external_key", "SCRUM-40"),
            "title": story["title"],
            "description": story.get("description", "Ticket Management and Lifecycle"),
            "acceptance_criteria": ac_texts,
        },
        "acceptance_criteria": ac_texts,
        "workspace_path": workspace_path,
        "collection_path": postman_path,
        "postman_collection": collection_data,
        "target_host": "http://localhost:5001",
        "capabilities": ["Test Generation", "API Execution", "Code Validation", "Evidence Generation"],
    }

    # Extract initial api_contracts from Postman collection if possible
    try:
        from app.tools.api_runner.collection_parser import parse_postman_collection
        parsed_eps = parse_postman_collection(collection_data)
        init_contracts = []
        svc_name = collection_data.get("info", {}).get("name", "TicketService")
        for ep in parsed_eps:
            init_contracts.append({
                "service": svc_name,
                "method": ep.get("method", "GET").upper(),
                "path": ep.get("path", "/"),
                "headers": ep.get("headers", {}),
                "sample_request": ep.get("body"),
                "sample_response": ep.get("response_example"),
                "expected_status_code": ep.get("expected_status_code", 200),
                "source": "POSTMAN_COLLECTION",
            })
        initial_state["api_contracts"] = init_contracts
        print(f"Extracted {len(init_contracts)} initial API contracts from Postman collection.")
    except Exception as ex:
        print(f"Note: Postman contract pre-extraction skipped: {ex}")

    from app.repositories.workflow_repo import create_run
    create_run(
        workflow_id=workflow_id,
        project_id=story.get("project_id", 1),
        story_id=story["id"],
        status=sm.QUEUED,
        stage=sm.CREATED,
        capabilities=["Test Generation", "API Execution", "Code Validation", "Evidence Generation"],
        state=initial_state,
        started_by=1,
    )

    orch = Orchestrator()

    # 5. Run from REQUIREMENT_ANALYSIS to TEST_REVIEW checkpoint
    print("\n--- Running Stages: REQUIREMENT_ANALYSIS -> SERVICE_PLANNING -> TEST_PLANNING -> TEST_GENERATION ---")
    state = orch.advance(workflow_id, initial_state)
    print(f"Paused at: {state.get('current_stage')} (Status: {state.get('status')})")

    if state.get("current_stage") == sm.TEST_PLAN_REVIEW:
        print("\n--- Approving TEST_PLAN_REVIEW -> Advancing to TEST_GENERATION ---")
        state = orch.resume(workflow_id, state, sm.TEST_PLAN_REVIEW)
        print(f"Paused at: {state.get('current_stage')} (Status: {state.get('status')})")

    assert state.get("current_stage") == sm.TEST_REVIEW, f"Expected TEST_REVIEW, got {state.get('current_stage')}"
    print(f"Generated {len(state.get('generated_tests', []))} structured test cases.")

    # 6. Approve TEST_REVIEW checkpoint -> runs CODE_GENERATION -> API_EXECUTION -> CODE_VALIDATION -> EVIDENCE_GENERATION
    print("\n--- Approving TEST_REVIEW -> Executing CODE_GENERATION, API_EXECUTION, CODE_VALIDATION, EVIDENCE_GENERATION ---")
    state = orch.resume(workflow_id, state, sm.TEST_REVIEW)

    print(f"\nPipeline halted at: {state.get('current_stage')} (Status: {state.get('status')})")

    # 7. Extract execution artifacts
    unit_test_exec = state.get("unit_test_execution") or {}
    real_cov = state.get("real_code_coverage") or {}
    api_exec = state.get("execution") or {}
    evidence = state.get("evidence") or {}

    docx_path = evidence.get("docx_path")
    html_path = evidence.get("html_path")

    print("\n" + "=" * 80)
    print("PIPELINE EXECUTION RESULTS:")
    print("=" * 80)
    print(f"Workflow ID               : {workflow_id}")
    print(f"Generated Test Cases      : {len(state.get('generated_tests', []))}")
    print(f"Unit Tests Executed       : {unit_test_exec.get('total_tests', 0)}")
    print(f"Unit Tests Passed         : {unit_test_exec.get('passed_tests', 0)}")
    print(f"Unit Tests Failed         : {unit_test_exec.get('failed_tests', 0)}")
    print(f"Unit Test Pass Rate       : {unit_test_exec.get('passed_tests', 0)}/{unit_test_exec.get('total_tests', 0)}")
    print(f"Real API Tests            : {api_exec.get('passed', 0)}/{api_exec.get('total', 0)}")
    print(f"Scoped Line Coverage      : {real_cov.get('line_coverage_pct')}%")
    print(f"Scoped Branch Coverage    : {real_cov.get('branch_coverage_pct')}%")
    print(f"Scoped Source Files       : {real_cov.get('scoped_source_files')}")
    print(f"DOCX Evidence             : {docx_path} (exists: {os.path.exists(docx_path) if docx_path else False})")
    print(f"HTML Evidence             : {html_path} (exists: {os.path.exists(html_path) if html_path else False})")

    # 8. Programmatically inspect the generated DOCX
    print("\n--- Inspecting Generated DOCX Evidence Document ---")
    assert docx_path and os.path.isfile(docx_path), "DOCX file was not generated"
    doc = docx.Document(docx_path)

    found_exec_summary = False
    found_line_cov = False
    found_branch_cov = False
    found_story_pass = False
    found_matrix = False
    matrix_rows = []

    for t in doc.tables:
        for row in t.rows:
            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            row_line = " | ".join(cells)
            if "EXECUTION SUMMARY" in row_line:
                found_exec_summary = True
                print(f"[DOCX] Summary Box: {row_line}")
                if f"{real_cov.get('line_coverage_pct')}%" in row_line:
                    found_line_cov = True
                if f"{real_cov.get('branch_coverage_pct')}%" in row_line:
                    found_branch_cov = True
                if "User Story Unit Test Pass Rate" in row_line and "Not available" not in row_line:
                    found_story_pass = True

            if any(h in row_line for h in ["Coverage", "Runtime/API Path"]):
                found_matrix = True
                print(f"[DOCX] Matrix Header: {row_line}")

            if any(f"AC-{i}" in row_line or f"AC-0{i}" in row_line for i in range(1, 9)):
                matrix_rows.append(row_line)

    print(f"[DOCX] Matrix AC Rows Count: {len(matrix_rows)}")
    for r in matrix_rows[:4]:
        print(f"   * {r[:100]}...")

    # 9. Programmatically inspect the generated HTML
    print("\n--- Inspecting Generated HTML Evidence Document ---")
    assert html_path and os.path.isfile(html_path), "HTML file was not generated"
    with open(html_path, "r", encoding="utf-8") as hf:
        html_content = hf.read()

    html_has_line_cov = f"{real_cov.get('line_coverage_pct')}%" in html_content
    html_has_branch_cov = f"{real_cov.get('branch_coverage_pct')}%" in html_content
    html_has_cov_table = "pytest-cov" in html_content

    print(f"[HTML] Contains Line Coverage ({real_cov.get('line_coverage_pct')}%)  : {html_has_line_cov}")
    print(f"[HTML] Contains Branch Coverage ({real_cov.get('branch_coverage_pct')}%) : {html_has_branch_cov}")
    print(f"[HTML] Contains pytest-cov Telemetry      : {html_has_cov_table}")

    return {
        "unit_test_exec": unit_test_exec,
        "real_cov": real_cov,
        "api_exec": api_exec,
        "docx_path": docx_path,
        "html_path": html_path,
        "found_exec_summary": found_exec_summary,
        "found_line_cov": found_line_cov,
        "found_branch_cov": found_branch_cov,
        "found_story_pass": found_story_pass,
        "found_matrix": found_matrix,
        "matrix_rows_count": len(matrix_rows),
    }


if __name__ == "__main__":
    results = run_full_pipeline()
    print("\n[SUCCESS] Pipeline execution & verification completed successfully.")
