"""Test case + execution persistence."""
import json
from app.extensions.db import query, execute


def insert_test_case(uuid, workflow_id, story_id, tc):
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
    return query("SELECT * FROM test_cases WHERE workflow_id=%s ORDER BY test_key", (workflow_id,))


def set_test_status(uuid, status):
    execute("UPDATE test_cases SET status=%s WHERE uuid=%s", (status, uuid))


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

