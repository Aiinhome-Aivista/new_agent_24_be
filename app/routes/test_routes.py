# pyrefly: ignore [missing-import]
from flask import Blueprint, request
from app.errors.handlers import ok, fail
from app.auth.decorators import require_auth, require_permission
from app.repositories.test_repo import list_test_cases, set_test_status, list_executions, list_code_quality

test_bp = Blueprint("tests", __name__)


@test_bp.route("/workflows/<workflow_id>/test-cases", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def test_cases(workflow_id):
    tcs = list_test_cases(workflow_id)
    from app.repositories.workflow_repo import get_run
    import json as _json
    run = get_run(workflow_id)
    coverage_matrix = []
    generation_summary = None
    contract_gaps = []
    if run:
        state = run.get("state_json") or {}
        if isinstance(state, str):
            try:
                state = _json.loads(state)
            except Exception:
                state = {}
        coverage_matrix = state.get("coverage_matrix", [])
        generation_summary = state.get("generation_summary")
        contract_gaps = state.get("contract_gaps", [])

    return ok({
        "test_cases": tcs,
        "coverage_matrix": coverage_matrix,
        "generation_summary": generation_summary,
        "contract_gaps": contract_gaps
    })


@test_bp.route("/test-cases/<uuid>/status", methods=["POST"])
@require_auth
@require_permission("test.review")
def update_test_status(uuid):
    body = request.get_json(silent=True) or {}
    status = body.get("status")
    if status not in ("APPROVED", "REJECTED", "MODIFIED", "AWAITING_REVIEW"):
        return fail("VALIDATION_ERROR", "Invalid status")
    set_test_status(uuid, status)
    return ok({}, f"Test case {status}")


@test_bp.route("/workflows/<workflow_id>/executions", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def executions(workflow_id):
    return ok({"executions": list_executions(workflow_id)})


@test_bp.route("/workflows/<workflow_id>/code-quality", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def code_quality(workflow_id):
    return ok({"code_quality": list_code_quality(workflow_id)})


@test_bp.route("/workflows/<workflow_id>/code-log", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def code_log(workflow_id):
    try:
        from app.repositories.workflow_repo import get_run
        import json as _json
        run = get_run(workflow_id)
        if not run:
            return fail("NOT_FOUND", "Workflow not found", 404)
        state = run.get("state_json") or {}
        if isinstance(state, str):
            try:
                state = _json.loads(state)
            except Exception:
                state = {}
        generation_log = state.get("code_generation")
        return ok({"code_log": generation_log})
    except Exception as e:
        print(f"[test_routes] Handled code_log error gracefully: {e}")
        return ok({"code_log": None})


@test_bp.route("/workflows/<workflow_id>/run-live-test", methods=["POST"])
@require_auth
@require_permission("workflow.read")
def run_live_test(workflow_id):
    try:
        from app.repositories.workflow_repo import get_run
        from app.tools.api_runner.runner import LiveApiRunner
        from app.tools.environment.live_runner import LiveEnvironmentManager
        import json as _json

        body = request.get_json(silent=True) or {}
        scenario = body.get("scenario") or {}
        environment = body.get("environment", "http://localhost:8080")
        
        # If localhost and workflow has workspace_path, ensure local server is alive
        if workflow_id and workflow_id != "direct":
            run = get_run(workflow_id)
            if run:
                state = run.get("state_json") or {}
                if isinstance(state, str):
                    try:
                        state = _json.loads(state)
                    except Exception:
                        state = {}
                workspace_path = state.get("workspace_path")
                
                if workspace_path and "localhost" in environment:
                    import urllib.parse
                    parsed_url = urllib.parse.urlparse(environment)
                    port = parsed_url.port if parsed_url.port else 8080
                    try:
                        manager = LiveEnvironmentManager(workspace_path, port=port)
                        manager.start_server()
                    except Exception as e:
                        print(f"[test_routes] LiveEnvironmentManager error: {e}")

        if not scenario:
            return fail("VALIDATION_ERROR", "Scenario data is required")

        run_result = LiveApiRunner().run(
            collection_path=None, 
            environment=environment, 
            test_cases=[scenario]
        )
        
        result_data = run_result.results[0] if run_result.results else {}
        return ok({"result": result_data}, "Live test executed")
    except Exception as e:
        print(f"[test_routes] Handled run_live_test error: {e}")
        return fail("EXECUTION_ERROR", str(e), 500)


@test_bp.route("/live-proxy", methods=["POST"])
def live_proxy():
    """Direct proxy runner for Postman UI testing."""
    try:
        from app.tools.api_runner.runner import LiveApiRunner
        body = request.get_json(silent=True) or {}
        scenario = body.get("scenario") or {}
        environment = body.get("environment", "http://localhost:8080")

        if not scenario:
            return fail("VALIDATION_ERROR", "Request specification is required")

        run_result = LiveApiRunner().run(
            collection_path=None,
            environment=environment,
            test_cases=[scenario]
        )

        result_data = run_result.results[0] if run_result.results else {}
        return ok({"result": result_data}, "Request executed")
    except Exception as e:
        print(f"[test_routes] Handled live_proxy error: {e}")
        return fail("EXECUTION_ERROR", str(e), 500)

