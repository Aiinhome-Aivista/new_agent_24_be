"""Test case + execution persistence with batching and transaction support."""
import json
import uuid as _uuid
from app.extensions.db import query, execute, get_db_connection
import app.extensions.db as _db_ext


_SCHEMA_CHECKED = False


def _is_db_stubbed():
    """Returns True if execute or query has been monkeypatched (e.g. in test suites)."""
    return execute != _db_ext.execute or query != _db_ext.query


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

        # Allow execution_runs to support standalone runs
        try:
            execute("ALTER TABLE execution_runs MODIFY COLUMN workflow_id CHAR(36) NULL")
        except Exception:
            pass

        exec_run_cols = [
            ("project_id", "BIGINT NULL"),
            ("story_id", "BIGINT NULL"),
            ("base_url", "VARCHAR(255) NULL"),
            ("collection_name", "VARCHAR(255) NULL"),
        ]
        for col_name, col_type in exec_run_cols:
            exists = query(f"SHOW COLUMNS FROM execution_runs LIKE '{col_name}'")
            if not exists:
                try:
                    execute(f"ALTER TABLE execution_runs ADD COLUMN {col_name} {col_type}")
                except Exception:
                    pass

        # Allow execution_results to store test_key directly
        res_exists = query("SHOW COLUMNS FROM execution_results LIKE 'test_key'")
        if not res_exists:
            try:
                execute("ALTER TABLE execution_results ADD COLUMN test_key VARCHAR(150) NULL")
            except Exception:
                pass

        _SCHEMA_CHECKED = True
    except Exception as e:
        print(f"[test_repo] Schema check warning: {e}")


def _extract_tc_params(uuid, workflow_id, story_id, tc):
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

    return (
        uuid, workflow_id, story_id, tc["test_key"], tc["scenario_type"], tc["title"],
        tc.get("description"), tc.get("expected_result"), tc.get("priority", "medium"),
        tc.get("risk", "medium"), tc.get("origin", "AI_GENERATED"),
        tc.get("status", "AWAITING_REVIEW"), tc.get("generated_code"),
        tc.get("target_language"), tc.get("framework"), resp_funcs_str, story_ref,
        req_spec_str, res_spec_str, test_type, precond_str, test_data_str,
        test_steps_str, grounding_str, requires_review, assumption_details, ac_ids_str, exp_status_int,
        test_data_source, resp_funcs_source
    )


def insert_test_case(uuid, workflow_id, story_id, tc):
    _ensure_schema()
    params = _extract_tc_params(uuid, workflow_id, story_id, tc)
    try:
        return execute("""INSERT INTO test_cases
            (uuid, workflow_id, story_id, test_key, scenario_type, title, description,
             expected_result, priority, risk, origin, status, generated_code, target_language, framework,
             responsible_functions, story_reference, request_spec, expected_response_spec,
             test_type, preconditions, test_data, test_steps, grounding_metadata,
             requires_review, assumption_details, acceptance_criteria_ids, expected_status_code,
             test_data_source, responsible_functions_source)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            params, return_id=True)
    except Exception:
        try:
            return execute("""INSERT INTO test_cases
                (uuid, workflow_id, story_id, test_key, scenario_type, title, description,
                 expected_result, priority, risk, origin, status, generated_code, target_language, framework,
                 responsible_functions, story_reference, request_spec, expected_response_spec)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                params[:19], return_id=True)
        except Exception:
            return execute("""INSERT INTO test_cases
                (uuid, workflow_id, story_id, test_key, scenario_type, title, description,
                 expected_result, priority, risk, origin, status, generated_code, target_language, framework)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                params[:15], return_id=True)


def save_test_cases_batch(workflow_id, story_id, test_cases):
    """Saves multiple test cases in a single database transaction."""
    _ensure_schema()
    if not test_cases:
        return
    if _is_db_stubbed():
        if story_id:
            execute("DELETE FROM test_cases WHERE workflow_id=%s", (workflow_id,))
        for tc in test_cases:
            tc_uuid = tc.get("uuid") or str(_uuid.uuid4())
            tc["uuid"] = tc_uuid
            insert_test_case(tc_uuid, workflow_id, story_id, tc)
        return
    with get_db_connection() as conn:
        cur = conn.cursor(dictionary=True)
        if story_id:
            cur.execute("DELETE FROM test_cases WHERE workflow_id=%s", (workflow_id,))
        for tc in test_cases:
            tc_uuid = tc.get("uuid") or str(_uuid.uuid4())
            tc["uuid"] = tc_uuid
            params = _extract_tc_params(tc_uuid, workflow_id, story_id, tc)
            try:
                cur.execute("""INSERT INTO test_cases
                    (uuid, workflow_id, story_id, test_key, scenario_type, title, description,
                     expected_result, priority, risk, origin, status, generated_code, target_language, framework,
                     responsible_functions, story_reference, request_spec, expected_response_spec,
                     test_type, preconditions, test_data, test_steps, grounding_metadata,
                     requires_review, assumption_details, acceptance_criteria_ids, expected_status_code,
                     test_data_source, responsible_functions_source)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    params)
            except Exception:
                cur.execute("""INSERT INTO test_cases
                    (uuid, workflow_id, story_id, test_key, scenario_type, title, description,
                     expected_result, priority, risk, origin, status, generated_code, target_language, framework,
                     responsible_functions, story_reference, request_spec, expected_response_spec)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    params[:19])


def _hydrate_test_cases(rows):
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


def list_test_cases(workflow_id):
    rows = query("SELECT * FROM test_cases WHERE workflow_id=%s ORDER BY test_key", (workflow_id,))
    return _hydrate_test_cases(rows)


def list_test_cases_by_story_id(story_id):
    _ensure_schema()
    rows = query("SELECT * FROM test_cases WHERE story_id=%s ORDER BY test_key", (story_id,))
    return _hydrate_test_cases(rows)


def list_test_cases_by_story_uuid(story_uuid):
    _ensure_schema()
    rows = query("""
        SELECT tc.* FROM test_cases tc
        INNER JOIN stories s ON s.id = tc.story_id
        WHERE s.uuid = %s
        ORDER BY tc.test_key
    """, (story_uuid,))
    return _hydrate_test_cases(rows)


def set_test_status(uuid, status):
    execute("UPDATE test_cases SET status=%s WHERE uuid=%s", (status, uuid))


def update_test_case_code(uuid, generated_code, status="CODE_GENERATED"):
    execute("UPDATE test_cases SET generated_code=%s, status=%s WHERE uuid=%s", (generated_code, status, uuid))


def update_test_case_code_by_key(workflow_id, test_key, generated_code, status="CODE_GENERATED"):
    execute("UPDATE test_cases SET generated_code=%s, status=%s WHERE workflow_id=%s AND test_key=%s",
            (generated_code, status, workflow_id, test_key))


def create_execution_run(uuid, workflow_id, runner, environment, collection, status, total, passed, failed, is_mock,
                         project_id=None, story_id=None, base_url=None, collection_name=None):
    _ensure_schema()
    try:
        return execute("""INSERT INTO execution_runs
            (uuid, workflow_id, project_id, story_id, base_url, collection_name, runner, environment, collection, status, total, passed, failed, is_mock, started_at, completed_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())""",
            (uuid, workflow_id, project_id, story_id, base_url, collection_name, runner, environment, collection, status, total, passed, failed, is_mock),
            return_id=True)
    except Exception:
        return execute("""INSERT INTO execution_runs
            (uuid, workflow_id, runner, environment, collection, status, total, passed, failed, is_mock, started_at, completed_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())""",
            (uuid, workflow_id, runner, environment, collection, status, total, passed, failed, is_mock),
            return_id=True)


def add_execution_result(uuid, run_id, test_case_id, status_code, passed, duration_ms, assertions, is_mock, test_key=None):
    try:
        return execute("""INSERT INTO execution_results
            (uuid, execution_run_id, test_case_id, test_key, status_code, passed, duration_ms, assertions, executed_at, is_mock)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s)""",
            (uuid, run_id, test_case_id, test_key, status_code, passed, duration_ms, json.dumps(assertions or [], default=str), is_mock),
            return_id=True)
    except Exception:
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


def save_execution_run_with_results(run_uuid, workflow_id, runner, environment, collection, status,
                                    total, passed, failed, is_mock, results,
                                    project_id=None, story_id=None, base_url=None, collection_name=None):
    """Saves execution run, child results, and raw requests/responses in a single transaction."""
    _ensure_schema()
    if _is_db_stubbed():
        run_id = create_execution_run(run_uuid, workflow_id, runner, environment, collection, status,
                                      total, passed, failed, is_mock, project_id, story_id, base_url, collection_name)
        for r in results:
            tc_id = r.get("test_case_id")
            res_id = add_execution_result(str(_uuid.uuid4()), run_id, tc_id, r.get("status_code"),
                                          1 if r.get("passed") else 0, r.get("duration_ms", 0), r.get("assertions"), is_mock,
                                          test_key=r.get("test_key"))
            req = r.get("request") or {}
            save_raw_request(res_id, req.get("method", "GET"), req.get("url", ""), req.get("headers"), req.get("body"))
            save_raw_response(res_id, r.get("status_code"), r.get("headers"), r.get("response_body"), None)
        return run_id

    with get_db_connection() as conn:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("""INSERT INTO execution_runs
                (uuid, workflow_id, project_id, story_id, base_url, collection_name, runner, environment, collection, status, total, passed, failed, is_mock, started_at, completed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())""",
                (run_uuid, workflow_id, project_id, story_id, base_url, collection_name, runner, environment, collection, status, total, passed, failed, is_mock))
        except Exception:
            cur.execute("""INSERT INTO execution_runs
                (uuid, workflow_id, runner, environment, collection, status, total, passed, failed, is_mock, started_at, completed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())""",
                (run_uuid, workflow_id, runner, environment, collection, status, total, passed, failed, is_mock))
        run_id = cur.lastrowid

        for r in results:
            tc_id = r.get("test_case_id")
            res_uuid = str(_uuid.uuid4())
            try:
                cur.execute("""INSERT INTO execution_results
                    (uuid, execution_run_id, test_case_id, test_key, status_code, passed, duration_ms, assertions, executed_at, is_mock)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s)""",
                    (res_uuid, run_id, tc_id, r.get("test_key"), r.get("status_code"), 1 if r.get("passed") else 0,
                     r.get("duration_ms", 0), json.dumps(r.get("assertions") or [], default=str), 1 if is_mock else 0))
            except Exception:
                cur.execute("""INSERT INTO execution_results
                    (uuid, execution_run_id, test_case_id, status_code, passed, duration_ms, assertions, executed_at, is_mock)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,NOW(),%s)""",
                    (res_uuid, run_id, tc_id, r.get("status_code"), 1 if r.get("passed") else 0,
                     r.get("duration_ms", 0), json.dumps(r.get("assertions") or [], default=str), 1 if is_mock else 0))
            result_id = cur.lastrowid

            req = r.get("request") or {}
            cur.execute("""INSERT INTO api_requests (execution_result_id, method, url, headers, body)
                           VALUES (%s,%s,%s,%s,%s)""",
                        (result_id, req.get("method", "GET"), req.get("url", ""),
                         json.dumps(req.get("headers") or {}, default=str), req.get("body")))

            cur.execute("""INSERT INTO api_responses (execution_result_id, status_code, headers, body, raw_log_reference)
                           VALUES (%s,%s,%s,%s,%s)""",
                        (result_id, r.get("status_code"), json.dumps(r.get("headers") or {}, default=str),
                         r.get("response_body"), None))
        return run_id


def list_executions(workflow_id, limit=20):
    runs = query("SELECT * FROM execution_runs WHERE workflow_id=%s ORDER BY created_at DESC LIMIT %s",
                 (workflow_id, limit))
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


def list_standalone_executions(project_id=None, story_id=None, limit=50):
    _ensure_schema()
    params = []
    where_clauses = []
    if project_id:
        where_clauses.append("r.project_id = %s")
        params.append(project_id)
    if story_id:
        where_clauses.append("r.story_id = %s")
        params.append(story_id)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    params.append(limit)

    sql = f"""
        SELECT r.*,
               p.name AS project_name,
               s.title AS story_title,
               s.external_key AS story_key
        FROM execution_runs r
        LEFT JOIN projects p ON p.id = r.project_id
        LEFT JOIN stories s ON s.id = r.story_id
        {where_sql}
        ORDER BY r.created_at DESC
        LIMIT %s
    """
    runs = query(sql, tuple(params))
    if not runs:
        return []
    for r in runs:
        r["total"] = r.get("total") or 0
        r["passed"] = r.get("passed") or 0
        r["failed"] = r.get("failed") or 0
    return runs


def get_execution_run(run_uuid):
    _ensure_schema()
    is_num = str(run_uuid).isdigit()
    run = query("""
        SELECT r.*,
               p.name AS project_name,
               s.title AS story_title,
               s.external_key AS story_key
        FROM execution_runs r
        LEFT JOIN projects p ON p.id = r.project_id
        LEFT JOIN stories s ON s.id = r.story_id
        WHERE r.uuid = %s OR r.id = %s
        LIMIT 1
    """, (run_uuid, int(run_uuid) if is_num else -1), fetchone=True)
    if not run:
        return None

    results = query("""
        SELECT res.*,
               tc.title AS test_case_title,
               tc.test_key AS tc_test_key,
               req.method AS req_method,
               req.url AS req_url,
               req.headers AS req_headers,
               req.body AS req_body,
               resp.status_code AS resp_status,
               resp.headers AS resp_headers,
               resp.body AS resp_body
        FROM execution_results res
        LEFT JOIN test_cases tc ON tc.id = res.test_case_id
        LEFT JOIN api_requests req ON req.execution_result_id = res.id
        LEFT JOIN api_responses resp ON resp.execution_result_id = res.id
        WHERE res.execution_run_id = %s
        ORDER BY res.id ASC
    """, (run["id"],))

    for res in (results or []):
        if isinstance(res.get("assertions"), str):
            try:
                res["assertions"] = json.loads(res["assertions"])
            except Exception:
                res["assertions"] = []
        if isinstance(res.get("req_headers"), str):
            try:
                res["req_headers"] = json.loads(res["req_headers"])
            except Exception:
                pass
        if isinstance(res.get("resp_headers"), str):
            try:
                res["resp_headers"] = json.loads(res["resp_headers"])
            except Exception:
                pass
        if not res.get("test_key"):
            res["test_key"] = res.get("tc_test_key") or f"TC-{res.get('id')}"

    run["results"] = results or []
    return run


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


def save_code_quality_run_with_issues(run_uuid, workflow_id, analyzer, score, passed, is_mock, issues):
    """Saves code quality run and all child issues in a single transaction."""
    if _is_db_stubbed():
        cq_id = create_code_quality_run(run_uuid, workflow_id, analyzer, score, passed, is_mock)
        for issue in issues:
            add_code_quality_issue(cq_id, issue.get("severity", "info"), issue.get("rule", "quality_rule"),
                                   issue.get("file", ""), issue.get("line", 1), issue.get("description", ""),
                                   issue.get("remediation", ""))
        return cq_id

    with get_db_connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("""INSERT INTO code_quality_runs
            (uuid, workflow_id, analyzer, score, passed, is_mock) VALUES (%s,%s,%s,%s,%s,%s)""",
            (run_uuid, workflow_id, analyzer, score, 1 if passed else 0, 1 if is_mock else 0))
        cq_id = cur.lastrowid
        for issue in issues:
            cur.execute("""INSERT INTO code_quality_issues
                (code_quality_run_id, severity, rule, file, line, description, remediation)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (cq_id, issue.get("severity", "info"), issue.get("rule", "quality_rule"),
                 issue.get("file", ""), issue.get("line", 1), issue.get("description", ""),
                 issue.get("remediation", "")))
        return cq_id


def list_code_quality(workflow_id, limit=20):
    runs = query("SELECT * FROM code_quality_runs WHERE workflow_id=%s ORDER BY created_at DESC LIMIT %s",
                 (workflow_id, limit))
    if not runs:
        return []
    for r in runs:
        issues = query("SELECT * FROM code_quality_issues WHERE code_quality_run_id=%s ORDER BY id ASC", (r["id"],))
        r["issues"] = issues or []
    return runs


def get_execution_run(workflow_id):
    """Retrieve ONLY the latest execution run with child results for a workflow."""
    if _is_db_stubbed():
        runs = list_executions(workflow_id)
        return runs[0] if runs else None
    latest_run = query("SELECT * FROM execution_runs WHERE workflow_id=%s ORDER BY created_at DESC LIMIT 1",
                       (workflow_id,), fetchone=True)
    if not latest_run:
        return None
    results = query("""
        SELECT r.*,
               req.method, req.url, req.headers AS req_headers, req.body AS req_body,
               resp.status_code AS resp_status, resp.headers AS resp_headers, resp.body AS resp_body
        FROM execution_results r
        LEFT JOIN api_requests req ON req.execution_result_id = r.id
        LEFT JOIN api_responses resp ON resp.execution_result_id = r.id
        WHERE r.execution_run_id = %s
        ORDER BY r.id ASC
    """, (latest_run["id"],))
    for res in results:
        if isinstance(res.get("assertions"), str):
            try:
                res["assertions"] = json.loads(res["assertions"])
            except Exception:
                res["assertions"] = []
    latest_run["results"] = results or []
    return latest_run


def get_code_quality_run(workflow_id):
    """Retrieve ONLY the latest code quality run with child issues for a workflow."""
    if _is_db_stubbed():
        runs = list_code_quality(workflow_id)
        return runs[0] if runs else None
    latest_run = query("SELECT * FROM code_quality_runs WHERE workflow_id=%s ORDER BY created_at DESC LIMIT 1",
                       (workflow_id,), fetchone=True)
    if not latest_run:
        return None
    issues = query("SELECT * FROM code_quality_issues WHERE code_quality_run_id=%s ORDER BY id ASC",
                   (latest_run["id"],))
    latest_run["issues"] = issues or []
    return latest_run
