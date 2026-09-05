"""
API Executor routes — Standalone testing of local or deployed APIs against user stories,
Postman / Bruno collections, or custom endpoints without requiring repository checkouts.
"""
import uuid as _uuid
import json
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
