"""
Deterministic API test runner. Executes real Bruno/Postman collections when configured;
otherwise a labeled MOCK runner produces clearly-marked demo results. The LLM is NEVER
involved in producing execution values.
"""
import subprocess
import json
import random
from app.config import Config


class ApiRunResult:
    def __init__(self, results, is_mock):
        self.results = results   # list of per-test dicts
        self.is_mock = is_mock


class NewmanRunner:
    """Real runner via `newman` (Postman) — requires newman on PATH and a collection file."""
    def run(self, collection_path, environment):
        proc = subprocess.run(
            ["newman", "run", collection_path, "-e", environment, "--reporters", "json"],
            capture_output=True, text=True, timeout=300,
        )
        report = json.loads(proc.stdout or "{}")
        results = []
        for execution in report.get("run", {}).get("executions", []):
            resp = execution.get("response", {}) or {}
            results.append({
                "status_code": resp.get("code"),
                "passed": all(a.get("error") is None for a in execution.get("assertions", [])),
                "duration_ms": resp.get("responseTime"),
                "assertions": [{"name": a.get("assertion"), "passed": a.get("error") is None}
                               for a in execution.get("assertions", [])],
                "request": {"method": execution.get("request", {}).get("method"),
                            "url": str(execution.get("request", {}).get("url"))},
                "response_body": resp.get("stream"),
            })
        return ApiRunResult(results, is_mock=False)


class MockApiRunner:
    """Labeled MOCK runner — deterministic demo results, never presented as a real run."""
    def run(self, collection_path, environment, test_cases=None):
        rng = random.Random(collection_path or "seed")
        results = []
        tests_to_run = test_cases if (test_cases and len(test_cases) > 0) else [None, None, None]
        for idx, tc in enumerate(tests_to_run):
            if isinstance(tc, dict):
                req = tc.get("request_spec") or {}
                res_spec = tc.get("expected_response_spec") or {}
                exp_status = res_spec.get("status_code", 200)
                method = req.get("method", "POST")
                url = req.get("endpoint", "/api/resource")
                assertions_list = res_spec.get("assertions", ["Response status code is expected"])
                tc_id = tc.get("id")
                tc_key = tc.get("test_key", f"TC-{idx+1:03d}")
            else:
                method = "POST"
                url = "/api/resource"
                exp_status = 200
                assertions_list = ["Response status code is expected"]
                tc_id = None
                tc_key = f"TC-{idx+1:03d}"

            # High pass rate for realistic demo executions
            passed = rng.random() > 0.15
            status_code = exp_status if passed else (500 if exp_status in (200, 201) else 200)
            
            built_assertions = []
            for a in (assertions_list[:3] if assertions_list else ["Status code is as expected"]):
                a_name = a if isinstance(a, str) else str(a)
                built_assertions.append({"name": a_name, "passed": passed})

            results.append({
                "test_case_id": tc_id,
                "test_key": tc_key,
                "status_code": status_code,
                "passed": passed,
                "duration_ms": rng.randint(35, 160),
                "assertions": built_assertions,
                "request": {"method": method, "url": url},
                "response_body": json.dumps({"_mock": True, "status": "SUCCESS" if passed else "FAILED", "code": status_code}),
            })
        return ApiRunResult(results, is_mock=True)


def get_runner():
    if Config.API_RUNNER == "newman":
        return NewmanRunner()
    return MockApiRunner()

