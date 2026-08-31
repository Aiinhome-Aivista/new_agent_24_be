"""Test case + execution persistence."""
import json
from app.extensions.db import query, execute


_SCHEMA_CHECKED = False


def _ensure_schema():
    """Ensure all industry-standard QA columns exist in test_cases table (runs once per process)."""
    global _SCHEMA_CHECKED
    if _SCHEMA_CHECKED:
        return
    try:
        column_defs = [
            ("responsible_functions", "TEXT NULL"),
            ("story_reference", "TEXT NULL"),
            ("request_spec", "TEXT NULL"),
            ("expected_response_spec", "TEXT NULL"),
            ("test_type", "VARCHAR(50) DEFAULT 'API'"),
            ("preconditions", "TEXT NULL"),
            ("test_data", "TEXT NULL"),
            ("test_steps", "TEXT NULL"),
            ("grounding_metadata", "TEXT NULL"),
            ("requires_review", "TINYINT(1) DEFAULT 0"),
            ("assumption_details", "TEXT NULL"),
            ("acceptance_criteria_ids", "TEXT NULL"),
            ("expected_status_code", "INT NULL"),
            ("test_data_source", "VARCHAR(50) DEFAULT 'AI_DERIVED'"),
            ("responsible_functions_source", "VARCHAR(50) DEFAULT 'UNKNOWN'"),
        ]
        for col_name, col_type in column_defs:
            exists = query(f"SHOW COLUMNS FROM test_cases LIKE '{col_name}'")
            if not exists:
                try:
                    execute(f"ALTER TABLE test_cases ADD COLUMN {col_name} {col_type}")
                except Exception as ex:
                    print(f"[test_repo] Alter column {col_name} note: {ex}")
        _SCHEMA_CHECKED = True
    except Exception as e:
        print(f"[test_repo] Schema check warning: {e}")


def insert_test_case(uuid, workflow_id, story_id, tc):
    _ensure_schema()
    resp_funcs = tc.get("responsible_functions", [])
    resp_funcs_str = json.dumps(resp_funcs) if isinstance(resp_funcs, list) else (str(resp_funcs) if resp_funcs else "[]")

    story_ref = tc.get("story_reference", "")
    req_spec = tc.get("request_spec")
    req_spec_str = json.dumps(req_spec) if isinstance(req_spec, dict) else (str(req_spec) if req_spec else None)

    res_spec = tc.get("expected_response_spec")
    res_spec_str = json.dumps(res_spec) if isinstance(res_spec, dict) else (str(res_spec) if res_spec else None)

    test_type = tc.get("test_type", "API")
    preconditions = tc.get("preconditions")
    precond_str = json.dumps(preconditions) if isinstance(preconditions, (list, dict)) else (str(preconditions) if preconditions else None)

    test_data = tc.get("test_data")
    test_data_str = json.dumps(test_data) if isinstance(test_data, (list, dict)) else (str(test_data) if test_data else None)

    test_steps = tc.get("test_steps")
    test_steps_str = json.dumps(test_steps) if isinstance(test_steps, (list, dict)) else (str(test_steps) if test_steps else None)

    grounding_meta = tc.get("grounding_metadata")
    grounding_str = json.dumps(grounding_meta) if isinstance(grounding_meta, dict) else (str(grounding_meta) if grounding_meta else None)

    requires_review = 1 if tc.get("requires_review") else 0
    assumption_details = tc.get("assumption_details")

    ac_ids = tc.get("acceptance_criteria_ids", [])
    ac_ids_str = json.dumps(ac_ids) if isinstance(ac_ids, list) else (str(ac_ids) if ac_ids else None)

    exp_status = tc.get("expected_status_code")
    if exp_status is None and res_spec and isinstance(res_spec, dict):
        exp_status = res_spec.get("status_code")
    try:
        exp_status_int = int(exp_status) if exp_status is not None and str(exp_status).isdigit() else None
    except Exception:
        exp_status_int = None

    test_data_source = tc.get("test_data_source", "AI_DERIVED")
    resp_funcs_source = tc.get("responsible_functions_source", "UNKNOWN")

    try:
        return execute("""INSERT INTO test_cases
            (uuid, workflow_id, story_id, test_key, scenario_type, title, description,
             expected_result, priority, risk, origin, status, generated_code, target_language, framework,
             responsible_functions, story_reference, request_spec, expected_response_spec,
             test_type, preconditions, test_data, test_steps, grounding_metadata,
             requires_review, assumption_details, acceptance_criteria_ids, expected_status_code,
             test_data_source, responsible_functions_source)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (uuid, workflow_id, story_id, tc["test_key"], tc["scenario_type"], tc["title"],
             tc.get("description"), tc.get("expected_result"), tc.get("priority", "medium"),
             tc.get("risk", "medium"), tc.get("origin", "AI_GENERATED"),
             tc.get("status", "AWAITING_REVIEW"), tc.get("generated_code"),
             tc.get("target_language"), tc.get("framework"), resp_funcs_str, story_ref,
             req_spec_str, res_spec_str, test_type, precond_str, test_data_str,
             test_steps_str, grounding_str, requires_review, assumption_details, ac_ids_str, exp_status_int,
             test_data_source, resp_funcs_source),
            return_id=True)
    except Exception:
        # Resilient fallback with subset of columns
        try:
            return execute("""INSERT INTO test_cases
                (uuid, workflow_id, story_id, test_key, scenario_type, title, description,
                 expected_result, priority, risk, origin, status, generated_code, target_language, framework,
                 responsible_functions, story_reference, request_spec, expected_response_spec)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (uuid, workflow_id, story_id, tc["test_key"], tc["scenario_type"], tc["title"],
                 tc.get("description"), tc.get("expected_result"), tc.get("priority", "medium"),
                 tc.get("risk", "medium"), tc.get("origin", "AI_GENERATED"),
                 tc.get("status", "AWAITING_REVIEW"), tc.get("generated_code"),
                 tc.get("target_language"), tc.get("framework"), resp_funcs_str, story_ref,
                 req_spec_str, res_spec_str), return_id=True)
        except Exception:
            return execute("""INSERT INTO test_cases
                (uuid, workflow_id, story_id, test_key, scenario_type, title, description,
                 expected_result, priority, risk, origin, status, generated_code, target_language, framework)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (uuid, workflow_id, story_id, tc["test_key"], tc["scenario_type"], tc["title"],
                 tc.get("description"), tc.get("expected_result"), tc.get("priority", "medium"),
                 tc.get("risk", "medium"), tc.get("origin", "AI_GENERATED"),
                 tc.get("status", "AWAITING_REVIEW"), tc.get("generated_code"),
                 tc.get("target_language"), tc.get("framework")), return_id=True)


def list_test_cases(workflow_id):
    rows = query("SELECT * FROM test_cases WHERE workflow_id=%s ORDER BY test_key", (workflow_id,))
    if not rows:
        return []
    for r in rows:
        for json_col in ("responsible_functions", "request_spec", "expected_response_spec",
                         "preconditions", "test_data", "test_steps", "grounding_metadata",
                         "acceptance_criteria_ids"):
            val = r.get(json_col)
            if val and isinstance(val, str):
                try:
                    r[json_col] = json.loads(val)
                except Exception:
                    pass
        if not r.get("responsible_functions"):
            r["responsible_functions"] = []
        if not r.get("test_type"):
            r["test_type"] = "API"
        if r.get("requires_review") is not None:
            r["requires_review"] = bool(r["requires_review"])
    return rows


def set_test_status(uuid, status):
    execute("UPDATE test_cases SET status=%s WHERE uuid=%s", (status, uuid))


def update_test_case_code(uuid, generated_code, status="CODE_GENERATED"):
    execute("UPDATE test_cases SET generated_code=%s, status=%s WHERE uuid=%s", (generated_code, status, uuid))


def update_test_case_code_by_key(workflow_id, test_key, generated_code, status="CODE_GENERATED"):
    execute("UPDATE test_cases SET generated_code=%s, status=%s WHERE workflow_id=%s AND test_key=%s",
            (generated_code, status, workflow_id, test_key))


def create_execution_run(uuid, workflow_id, runner, environment, collection, status, total, passed, failed, is_mock):
    return execute("""INSERT INTO execution_runs
        (uuid, workflow_id, runner, environment, collection, status, total, passed, failed, is_mock, started_at, completed_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())""",
        (uuid, workflow_id, runner, environment, collection, status, total, passed, failed, is_mock),
        return_id=True)


def add_execution_result(uuid, run_id, test_case_id, status_code, passed, duration_ms, assertions, is_mock):
    return execute("""INSERT INTO execution_results
        (uuid, execution_run_id, test_case_id, status_code, passed, duration_ms, assertions, executed_at, is_mock)
        VALUES (%s,%s,%s,%s,%s,%s,%s,NOW(),%s)""",
        (uuid, run_id, test_case_id, status_code, passed, duration_ms, json.dumps(assertions or [], default=str), is_mock),
        return_id=True)


def save_raw_request(result_id, method, url, headers, body):
    execute("""INSERT INTO api_requests (execution_result_id, method, url, headers, body)
               VALUES (%s,%s,%s,%s,%s)""",
            (result_id, method, url, json.dumps(headers or {}, default=str), body))


def save_raw_response(result_id, status_code, headers, body, raw_ref):
    execute("""INSERT INTO api_responses (execution_result_id, status_code, headers, body, raw_log_reference)
               VALUES (%s,%s,%s,%s,%s)""",
            (result_id, status_code, json.dumps(headers or {}, default=str), body, raw_ref))



def list_executions(workflow_id):
    runs = query("SELECT * FROM execution_runs WHERE workflow_id=%s ORDER BY created_at DESC", (workflow_id,))
    if not runs:
        return []
    for r in runs:
        results = query("""
            SELECT r.*,
                   req.method, req.url, req.headers AS req_headers, req.body AS req_body,
                   resp.status_code AS resp_status, resp.headers AS resp_headers, resp.body AS resp_body
            FROM execution_results r
            LEFT JOIN api_requests req ON req.execution_result_id = r.id
            LEFT JOIN api_responses resp ON resp.execution_result_id = r.id
            WHERE r.execution_run_id = %s
            ORDER BY r.id ASC
        """, (r["id"],))
        for res in results:
            if isinstance(res.get("assertions"), str):
                try:
                    res["assertions"] = json.loads(res["assertions"])
                except Exception:
                    res["assertions"] = []
        r["results"] = results or []
    return runs


def create_code_quality_run(uuid, workflow_id, analyzer, score, passed, is_mock):
    return execute("""INSERT INTO code_quality_runs
        (uuid, workflow_id, analyzer, score, passed, is_mock) VALUES (%s,%s,%s,%s,%s,%s)""",
        (uuid, workflow_id, analyzer, score, 1 if passed else 0, 1 if is_mock else 0),
        return_id=True)


def add_code_quality_issue(run_id, severity, rule, file, line, description, remediation):
    execute("""INSERT INTO code_quality_issues
        (code_quality_run_id, severity, rule, file, line, description, remediation)
        VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (run_id, severity, rule, file, line, description, remediation))


def list_code_quality(workflow_id):
    runs = query("SELECT * FROM code_quality_runs WHERE workflow_id=%s ORDER BY created_at DESC", (workflow_id,))
    if not runs:
        return []
    for r in runs:
        issues = query("SELECT * FROM code_quality_issues WHERE code_quality_run_id=%s ORDER BY id ASC", (r["id"],))
        r["issues"] = issues or []
    return runs


def get_execution_run(workflow_id):
    """Retrieve the latest execution run with child results for a workflow."""
    runs = list_executions(workflow_id)
    return runs[0] if runs else None


def get_code_quality_run(workflow_id):
    """Retrieve the latest code quality run with child issues for a workflow."""
    runs = list_code_quality(workflow_id)
    return runs[0] if runs else None


