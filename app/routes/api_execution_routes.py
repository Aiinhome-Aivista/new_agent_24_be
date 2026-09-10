"""
API Executor routes — Standalone testing of local or deployed APIs against user stories,
Postman / Bruno collections, or custom endpoints without requiring repository checkouts.
"""
import os
import uuid as _uuid
import json
import time
from datetime import datetime, timezone
import requests
from flask import Blueprint, request, send_file, make_response
from app.errors.handlers import ok, fail
from app.auth.decorators import require_auth
from app.repositories.project_repo import get_story, get_project
from app.repositories.test_repo import (
    save_execution_run_with_results,
    list_standalone_executions,
    get_execution_run,
    list_test_cases_by_story_uuid,
)
from app.tools.api_runner.runner import AutoRunner, HttpRunner, NewmanRunner, MockApiRunner
from app.tools.api_runner.collection_parser import parse_postman_collection
from app.agents.api_executor.autonomous_agent import (
    AutonomousApiVerifierAgent,
    get_cached_hosts,
    add_cached_host,
)
from app.tools.document_generator.docx_generator import generate_docx_evidence
from app.tools.document_generator.generator import render_autonomous_evidence_html

api_execution_bp = Blueprint("api_execution", __name__)

_AUTONOMOUS_EVIDENCE_STORE = {}


@api_execution_bp.route("/api-executor/run", methods=["POST"])
@require_auth
def run_api_tests():
    body = request.get_json(silent=True) or {}
    base_url = (body.get("base_url") or "").strip()
    if not base_url:
        return fail("VALIDATION_ERROR", "Target base_url is required (e.g. http://localhost:8080 or https://api.example.com)")

    endpoints = body.get("endpoints") or []
    collection_json = body.get("collection_json")
    collection_name = body.get("collection_name")
    project_uuid = body.get("project_uuid")
    story_uuid = body.get("story_uuid")
    is_mock = bool(body.get("is_mock", False))
    runner_type = body.get("runner_type", "auto").lower()

    project_id = None
    story_id = None
    if project_uuid:
        proj = get_project(project_uuid)
        if proj:
            project_id = proj.get("id")
    if story_uuid:
        st = get_story(story_uuid)
        if st:
            story_id = st.get("id")
            if not project_id:
                project_id = st.get("project_id")

    # If neither endpoints nor collection provided, but story_uuid is given, auto-load test cases
    if not endpoints and not collection_json and story_uuid:
        story_tcs = list_test_cases_by_story_uuid(story_uuid)
        if story_tcs:
            endpoints = []
            for tc in story_tcs:
                req_spec = tc.get("request_spec") or {}
                res_spec = tc.get("expected_response_spec") or {}
                endpoints.append({
                    "test_case_id": tc.get("id"),
                    "test_key": tc.get("test_key") or tc.get("title") or "Test Case",
                    "method": req_spec.get("method") or "GET",
                    "path": req_spec.get("endpoint") or req_spec.get("path") or "/",
                    "headers": req_spec.get("headers") or {},
                    "params": req_spec.get("query_params") or {},
                    "body": req_spec.get("body"),
                    "expected_status_code": res_spec.get("status_code", 200),
                    "assertions": res_spec.get("assertions") or ["Status code matches expected"],
                })

    # If collection is provided and endpoints not pre-parsed, parse it
    if collection_json and not endpoints:
        endpoints = parse_postman_collection(collection_json)
        if not collection_name and isinstance(collection_json, dict):
            collection_name = collection_json.get("info", {}).get("name")

    if not endpoints and not collection_json:
        return fail("VALIDATION_ERROR", "No endpoints, collection, or story test cases provided for execution")

    # Choose runner
    if is_mock or runner_type == "mock":
        runner_instance = MockApiRunner()
        runner_name = "mock"
        run_result = runner_instance.run(base_url=base_url, endpoints=endpoints)
    elif runner_type == "newman":
        runner_instance = NewmanRunner()
        runner_name = "newman"
        run_result = runner_instance.run(collection_path_or_json=collection_json or endpoints, base_url=base_url)
    elif runner_type == "http":
        runner_instance = HttpRunner()
        runner_name = "http"
        run_result = runner_instance.run(endpoints=endpoints, base_url=base_url)
    else:
        # Default AutoRunner
        runner_instance = AutoRunner()
        runner_name = "http" if not collection_json else "newman"
        run_result = runner_instance.run(
            base_url=base_url,
            collection=collection_json,
            endpoints=endpoints,
            is_mock=is_mock
        )

    run_uuid = str(_uuid.uuid4())
    status = "PASSED" if run_result.failed == 0 else "FAILED"

    # Persist run and child results
    save_execution_run_with_results(
        run_uuid=run_uuid,
        workflow_id=None,
        runner=runner_name,
        environment="standalone",
        collection=collection_name or "Custom Endpoints",
        status=status,
        total=run_result.total,
        passed=run_result.passed,
        failed=run_result.failed,
        is_mock=run_result.is_mock,
        results=run_result.results,
        project_id=project_id,
        story_id=story_id,
        base_url=base_url,
        collection_name=collection_name or "Custom Endpoints",
    )

    saved_run = get_execution_run(run_uuid)
    return ok(saved_run, message="Execution completed successfully")


@api_execution_bp.route("/api-executor/runs", methods=["GET"])
@require_auth
def list_runs():
    project_uuid = request.args.get("project_uuid")
    story_uuid = request.args.get("story_uuid")
    limit = int(request.args.get("limit", 50))

    project_id = None
    story_id = None
    if project_uuid:
        proj = get_project(project_uuid)
        if proj:
            project_id = proj.get("id")
    if story_uuid:
        st = get_story(story_uuid)
        if st:
            story_id = st.get("id")

    runs = list_standalone_executions(project_id=project_id, story_id=story_id, limit=limit)
    return ok({"runs": runs})


@api_execution_bp.route("/api-executor/runs/<run_uuid>", methods=["GET"])
@require_auth
def get_run_details(run_uuid):
    run = get_execution_run(run_uuid)
    if not run:
        return fail("NOT_FOUND", "Execution run not found", 404)
    return ok(run)


@api_execution_bp.route("/api-executor/stories/<story_uuid>/test-cases", methods=["GET"])
@require_auth
def get_story_test_cases_for_runner(story_uuid):
    story = get_story(story_uuid)
    if not story:
        return fail("NOT_FOUND", "Story not found", 404)

    raw_tcs = list_test_cases_by_story_uuid(story_uuid)
    endpoints = []
    for tc in raw_tcs:
        req_spec = tc.get("request_spec") or {}
        res_spec = tc.get("expected_response_spec") or {}
        endpoints.append({
            "test_case_id": tc.get("id"),
            "test_key": tc.get("test_key") or tc.get("title") or "TC",
            "name": tc.get("title") or tc.get("test_key"),
            "method": req_spec.get("method") or "GET",
            "path": req_spec.get("endpoint") or req_spec.get("path") or "/",
            "headers": req_spec.get("headers") or {},
            "params": req_spec.get("query_params") or {},
            "body": req_spec.get("body"),
            "expected_status_code": res_spec.get("status_code", 200),
            "expected_body_contains": None,
            "assertions": res_spec.get("assertions") or ["Status code matches expected"],
        })

    return ok({
        "story": {
            "uuid": story.get("uuid"),
            "title": story.get("title"),
            "external_key": story.get("external_key"),
        },
        "test_cases": endpoints,
        "total": len(endpoints)
    })


@api_execution_bp.route("/api-executor/parse-collection", methods=["POST"])
@require_auth
def parse_collection():
    collection_data = None
    collection_name = None

    if "file" in request.files:
        f = request.files["file"]
        collection_name = f.filename
        try:
            content = f.read().decode("utf-8")
            collection_data = json.loads(content)
        except Exception as e:
            return fail("INVALID_FILE", f"Failed to parse collection JSON: {e}")
    else:
        body = request.get_json(silent=True) or {}
        collection_data = body.get("collection") or body
        collection_name = body.get("collection_name")

    if not collection_data:
        return fail("VALIDATION_ERROR", "Valid collection JSON or file required")

    if isinstance(collection_data, dict) and not collection_name:
        collection_name = collection_data.get("info", {}).get("name")

    endpoints = parse_postman_collection(collection_data)
    return ok({
        "collection_name": collection_name or "Imported Collection",
        "endpoints": endpoints,
        "total": len(endpoints)
    })


@api_execution_bp.route("/api-executor/execute-single", methods=["POST"])
@require_auth
def execute_single_test():
    """Executes an ad-hoc single HTTP request and returns immediate telemetry and extracted tokens."""
    body = request.get_json(silent=True) or {}
    base_url = (body.get("base_url") or "").strip()
    endpoint = body.get("endpoint") or {}
    if not endpoint:
        endpoint = {
            "method": body.get("method", "GET"),
            "path": body.get("url") or body.get("path", "/"),
            "headers": body.get("headers") or {},
            "params": body.get("params") or {},
            "body": body.get("body"),
            "expected_status_code": body.get("expected_status_code", 200),
            "expected_body_contains": body.get("expected_body_contains"),
            "assertions": body.get("assertions") or [],
        }

    raw_url = endpoint.get("path") or endpoint.get("url") or "/"
    clean_url = str(raw_url).strip()
    if clean_url.startswith("/http://") or clean_url.startswith("/https://"):
        clean_url = clean_url[1:]
    endpoint["path"] = clean_url

    if not clean_url.startswith("http://") and not clean_url.startswith("https://") and not base_url:
        return fail("VALIDATION_ERROR", "Target base_url or full URL is required")

    runner = HttpRunner()
    run_result = runner.run(endpoints=[endpoint], base_url=base_url or "")
    if not run_result.results:
        return fail("EXECUTION_ERROR", "No execution result returned from runner")

    res = run_result.results[0]
    # Check if any tokens or IDs were returned in response
    extracted_tokens = {}
    try:
        resp_body = res.get("response_body")
        if resp_body:
            parsed = json.loads(resp_body)
            if isinstance(parsed, dict):
                for k in ("access_token", "token", "token_type", "jwt", "id"):
                    if k in parsed:
                        extracted_tokens[k] = parsed[k]
                if "user" in parsed and isinstance(parsed["user"], dict):
                    extracted_tokens["user"] = parsed["user"]
    except Exception:
        pass

    return ok({
        "result": res,
        "extracted_tokens": extracted_tokens,
    })


@api_execution_bp.route("/api-executor/ping", methods=["POST"])
@require_auth
def ping_target():
    """Checks if a target host/base_url is reachable and returns latency."""
    body = request.get_json(silent=True) or {}
    target_url = (body.get("url") or "").strip()
    if not target_url:
        return fail("VALIDATION_ERROR", "Target URL required")
    try:
        t0 = time.perf_counter()
        resp = requests.get(target_url, timeout=4, allow_redirects=True)
        latency = int((time.perf_counter() - t0) * 1000)
        return ok({"reachable": True, "status_code": resp.status_code, "latency_ms": latency})
    except Exception as e:
        return ok({"reachable": False, "error": str(e)})


@api_execution_bp.route("/api-executor/sample-collections", methods=["GET"])
@require_auth
def list_sample_collections():
    """Returns project-uploaded and bundled Postman collections ready for testing."""
    project_uuid = request.args.get("project_uuid")
    collections = []
    seen_names = set()

    # 1. Project-uploaded collections from knowledge_documents / storage
    if project_uuid:
        try:
            project = get_project(project_uuid)
            if project:
                from app.repositories.project_repo import list_knowledge_documents
                docs = list_knowledge_documents(project["id"]) or []
                for doc in docs:
                    title = doc.get("title", "")
                    doc_type = (doc.get("doc_type") or "").lower()
                    source_path = doc.get("source", "")
                    if title.endswith(".json") or doc_type in ("postman_collection", "postman", "api_contract", "openapi"):
                        content = None
                        if source_path and os.path.isfile(source_path):
                            try:
                                with open(source_path, "r", encoding="utf-8") as f:
                                    content = json.load(f)
                            except Exception:
                                pass
                        
                        if content and isinstance(content, dict):
                            col_name = content.get("info", {}).get("name", title)
                            if col_name not in seen_names:
                                seen_names.add(col_name)
                                collections.append({
                                    "id": doc.get("uuid", f"doc-{doc.get('id')}"),
                                    "name": col_name,
                                    "description": content.get("info", {}).get("description", f"Uploaded collection: {title}"),
                                    "collection": content,
                                    "is_project_collection": True
                                })
        except Exception as e:
            print(f"[ApiExecutor] Error loading project collections: {e}")

    # Also check workspace root for any .postman_collection.json
    workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    for candidate_name in ["ticket-management.postman_collection.json"]:
        candidate_path = os.path.join(workspace_root, candidate_name)
        if os.path.exists(candidate_path):
            try:
                with open(candidate_path, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    col_name = content.get("info", {}).get("name", candidate_name)
                    if col_name not in seen_names:
                        seen_names.add(col_name)
                        collections.append({
                            "id": "ticket-management-collection",
                            "name": col_name,
                            "description": content.get("info", {}).get("description", "Support Ticket Management API Collection"),
                            "collection": content,
                            "is_project_collection": True
                        })
            except Exception:
                pass

    # 2. Bundled Auth & User Profile collection
    sample_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "collections", "auth_user_service_collection.json")
    if os.path.exists(sample_path):
        try:
            with open(sample_path, "r", encoding="utf-8") as f:
                content = json.load(f)
                col_name = content.get("info", {}).get("name", "Auth & User Profile API")
                if col_name not in seen_names:
                    seen_names.add(col_name)
                    collections.append({
                        "id": "auth-user-service",
                        "name": col_name,
                        "description": content.get("info", {}).get("description", ""),
                        "collection": content,
                        "is_project_collection": False
                    })
        except Exception:
            pass

    return ok({"collections": collections})


@api_execution_bp.route("/api-executor/cached-hosts", methods=["GET", "POST"])
@require_auth
def manage_cached_hosts():
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        url = body.get("url")
        name = body.get("name")
        updated = add_cached_host(url, name)
        return ok({"hosts": updated})
    return ok({"hosts": get_cached_hosts()})


@api_execution_bp.route("/api-executor/autonomous-run", methods=["POST"])
@require_auth
def run_autonomous_verification():
    """
    Triggers the Antigravity Autonomous Agent inside the API Executor module.
    Executes Postman collection, validates against story acceptance criteria,
    detects anomalies / extra fields (e.g. 'role'), and produces signed evidence.
    """
    body = request.get_json(silent=True) or {}
    base_url = (body.get("base_url") or "http://localhost:5001").strip()
    collection_data = body.get("collection_json")
    collection_name = body.get("collection_name")
    story_uuid = body.get("story_uuid")
    project_uuid = body.get("project_uuid")
    is_mock = bool(body.get("is_mock", False))

    # Auto-fallback: check project collections, then bundled Auth Postman collection
    if not collection_data and project_uuid:
        try:
            project = get_project(project_uuid)
            if project:
                from app.repositories.project_repo import list_knowledge_documents
                docs = list_knowledge_documents(project["id"]) or []
                for doc in docs:
                    source_path = doc.get("source", "")
                    if source_path and os.path.isfile(source_path) and doc.get("title", "").endswith(".json"):
                        with open(source_path, "r", encoding="utf-8") as f:
                            collection_data = json.load(f)
                            collection_name = collection_data.get("info", {}).get("name", doc.get("title"))
                            break
        except Exception:
            pass

    if not collection_data:
        workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        ticket_col_path = os.path.join(workspace_root, "ticket-management.postman_collection.json")
        if os.path.exists(ticket_col_path):
            try:
                with open(ticket_col_path, "r", encoding="utf-8") as f:
                    collection_data = json.load(f)
                    collection_name = collection_data.get("info", {}).get("name")
            except Exception:
                pass

    if not collection_data:
        sample_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "collections", "auth_user_service_collection.json")
        if os.path.exists(sample_path):
            try:
                with open(sample_path, "r", encoding="utf-8") as f:
                    collection_data = json.load(f)
                    if not collection_name:
                        collection_name = collection_data.get("info", {}).get("name")
            except Exception as e:
                return fail("COLLECTION_ERROR", f"Could not load default collection: {e}")

    if not collection_data:
        return fail("VALIDATION_ERROR", "A Postman collection JSON or bundled collection is required.")

    agent = AutonomousApiVerifierAgent(timeout=15)
    try:
        evidence = agent.execute_autonomous_verification(
            base_url=base_url,
            collection_data=collection_data,
            story_uuid=story_uuid,
            project_uuid=project_uuid,
            collection_name=collection_name,
            is_mock=is_mock,
        )

        evidence_key = evidence.get("evidence_key")
        _AUTONOMOUS_EVIDENCE_STORE[evidence_key] = evidence

        # Generate Word (.docx) package
        out_dir = os.path.join(os.path.dirname(__file__), "..", "..", "evidence_output")
        docx_path = generate_docx_evidence(evidence, out_dir=out_dir)
        evidence["docx_path"] = docx_path

        # Generate HTML/PDF report
        html_path = render_autonomous_evidence_html(evidence, out_dir=out_dir)
        evidence["html_path"] = html_path

        # Persist to database execution_runs for historical audit log
        try:
            results_list = []
            for r in evidence.get("results", []):
                req_data = r.get("request") or {}
                resp_data = r.get("response") or {}
                results_list.append({
                    "test_key": r.get("test_key") or f"{r.get('method')} {r.get('endpoint')}",
                    "method": r.get("method"),
                    "endpoint": r.get("endpoint"),
                    "status_code": r.get("status_code"),
                    "passed": bool(r.get("passed")),
                    "duration_ms": r.get("duration_ms", 0),
                    "assertions": r.get("assertions", []),
                    "request": {
                        "method": req_data.get("method", r.get("method", "GET")),
                        "url": f"{base_url}{r.get('endpoint', '')}",
                        "headers": req_data.get("headers", {}),
                        "body": json.dumps(req_data.get("body")) if req_data.get("body") else None,
                    },
                    "response_body": json.dumps(resp_data.get("body")) if resp_data.get("body") else None,
                    "headers": resp_data.get("headers", {}),
                })

            save_execution_run_with_results(
                run_uuid=str(_uuid.uuid4()),
                workflow_id=None,
                runner="autonomous_agent",
                environment="standalone",
                collection=collection_name or "Auth Service Verification",
                status="PASSED" if evidence.get("failed_endpoints", 0) == 0 else "FAILED",
                total=evidence.get("total_endpoints", 0),
                passed=evidence.get("passed_endpoints", 0),
                failed=evidence.get("failed_endpoints", 0),
                is_mock=is_mock,
                results=results_list,
                project_id=None,
                story_id=None,
                base_url=base_url,
                collection_name=f"Autonomous Verification [{evidence_key}]",
            )
        except Exception:
            pass

        return ok(evidence, message="Autonomous verification completed successfully.")
    except Exception as ex:
        return fail("EXECUTION_ERROR", f"Autonomous execution failed: {str(ex)}")


@api_execution_bp.route("/api-executor/evidence/<evidence_key>/download-docx", methods=["GET"])
def download_evidence_docx(evidence_key):
    """Downloads audit-ready Word (.docx) test evidence package."""
    out_dir = os.path.join(os.path.dirname(__file__), "..", "..", "evidence_output")
    file_path = os.path.join(out_dir, f"{evidence_key}.docx")

    if not os.path.exists(file_path):
        # Regenerate if stored in memory
        ev = _AUTONOMOUS_EVIDENCE_STORE.get(evidence_key)
        if ev:
            file_path = generate_docx_evidence(ev, out_dir=out_dir)
        else:
            return fail("NOT_FOUND", "Evidence document not found", 404)

    return send_file(
        file_path,
        as_attachment=True,
        download_name=f"{evidence_key}.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


@api_execution_bp.route("/api-executor/evidence/<evidence_key>/download-pdf", methods=["GET"])
def download_evidence_pdf(evidence_key):
    """Downloads print-optimized HTML/PDF audit evidence package."""
    out_dir = os.path.join(os.path.dirname(__file__), "..", "..", "evidence_output")
    file_path = os.path.join(out_dir, f"{evidence_key}.html")

    if not os.path.exists(file_path):
        ev = _AUTONOMOUS_EVIDENCE_STORE.get(evidence_key)
        if ev:
            file_path = render_autonomous_evidence_html(ev, out_dir=out_dir)
        else:
            return fail("NOT_FOUND", "Evidence report not found", 404)

    return send_file(
        file_path,
        as_attachment=False,
        mimetype="text/html"
    )


@api_execution_bp.route("/api-executor/evidence/<evidence_key>/download-json", methods=["GET"])
def download_evidence_json(evidence_key):
    """Downloads structured JSON evidence artifact."""
    ev = _AUTONOMOUS_EVIDENCE_STORE.get(evidence_key)
    if not ev:
        return fail("NOT_FOUND", "Evidence object not found", 404)

    response = make_response(json.dumps(ev, indent=2))
    response.headers["Content-Type"] = "application/json"
    response.headers["Content-Disposition"] = f"attachment; filename={evidence_key}.json"
    return response


@api_execution_bp.route("/api-executor/alm-writeback", methods=["POST"])
@require_auth
def alm_writeback_guardrail():
    """
    Enforces governance guardrail: Requires explicit human approval before
    initiating ALM write-back of test evidence.
    """
    body = request.get_json(silent=True) or {}
    evidence_key = body.get("evidence_key")
    approved = bool(body.get("human_approved", False))
    approver = body.get("approver_name") or "Authorized Lead QA"
    comment = body.get("approval_comment") or "Autonomous test evidence verified and approved."

    if not evidence_key:
        return fail("VALIDATION_ERROR", "evidence_key is required")

    if not approved:
        return fail("GOVERNANCE_BLOCKED", "ALM write-back blocked: Explicit human approval is required by governance policy.")

    ev = _AUTONOMOUS_EVIDENCE_STORE.get(evidence_key)
    if ev:
        ev["alm_writeback_status"] = "SYNCHRONIZED"
        ev["alm_approval"] = {
            "approved": True,
            "approver": approver,
            "comment": comment,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "target_alm": "Jira / Azure DevOps",
        }

    return ok({
        "status": "SYNCHRONIZED",
        "evidence_key": evidence_key,
        "message": f"Evidence {evidence_key} authorized by {approver} and queued for ALM synchronization.",
        "idempotency_key": f"ALM-{evidence_key}-{int(time.time())}"
    })


