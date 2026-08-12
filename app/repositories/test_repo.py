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
    return query("SELECT * FROM execution_runs WHERE workflow_id=%s ORDER BY created_at DESC", (workflow_id,))


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
