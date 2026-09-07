"""
API Executor routes — Standalone testing of local or deployed APIs against user stories,
Postman / Bruno collections, or custom endpoints without requiring repository checkouts.
"""
import uuid as _uuid
import json
import time
import requests
from flask import Blueprint, request
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

api_execution_bp = Blueprint("api_execution", __name__)


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

