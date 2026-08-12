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
    def run(self, collection_path, environment):
        rng = random.Random(collection_path or "seed")
        results = []
        for i in range(3):
            passed = rng.random() > 0.25
            results.append({
                "status_code": 200 if passed else 422,
                "passed": passed,
                "duration_ms": rng.randint(40, 180),
                "assertions": [{"name": "status is expected", "passed": passed}],
                "request": {"method": "POST", "url": "/api/payments/authorize"},
                "response_body": json.dumps({"_mock": True, "authCode": "MOCK-AUTH", "status": "AUTHORIZED" if passed else "DECLINED"}),
            })
        return ApiRunResult(results, is_mock=True)


def get_runner():
    if Config.API_RUNNER == "newman":
        return NewmanRunner()
    return MockApiRunner()
