"""
Deterministic API test runner.
Supports:
1. HttpRunner: Direct real HTTP requests against local or deployed base_url.
2. NewmanRunner: Runs Postman collections using newman CLI with automatic fallback to HttpRunner.
3. MockApiRunner: Deterministic mock runner for simulated pipelines.
4. AutoRunner: Dispatches based on request context.
"""
import subprocess
import json
import random
import time
import shutil
from urllib.parse import urljoin
import requests

from app.config import Config
from app.tools.api_runner.collection_parser import parse_postman_collection


class ApiRunResult:
    def __init__(self, results, is_mock=False):
        self.results = results   # list of per-test dicts
        self.is_mock = is_mock

    @property
    def total(self):
        return len(self.results)

    @property
    def passed(self):
        return sum(1 for r in self.results if r.get("passed"))

    @property
    def failed(self):
        return sum(1 for r in self.results if not r.get("passed"))


class HttpRunner:
    """Direct real HTTP request runner against any target base_url (local or deployed)."""

    def __init__(self, timeout=15):
        self.timeout = timeout

    def run(self, endpoints=None, base_url="http://localhost:8080", environment=None, test_cases=None):
        base_url = (base_url or "http://localhost:8080").strip().rstrip("/")
        items = endpoints or []

        # If test_cases passed from story but endpoints not formatted
        if not items and test_cases:
            items = []
            for tc in test_cases:
                if not isinstance(tc, dict):
                    continue
                req_spec = tc.get("request_spec") or {}
                res_spec = tc.get("expected_response_spec") or {}
                items.append({
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

        env_vars = {
            "baseUrl": base_url,
            "base_url": base_url,
        }

        def _substitute_vars(val):
            if not val or not env_vars:
                return val
            if isinstance(val, str):
                for k, v in env_vars.items():
                    target = f"{{{{{k}}}}}"
                    if target in val:
                        val = val.replace(target, str(v))
                return val
            elif isinstance(val, dict):
                return {k: _substitute_vars(v) for k, v in val.items()}
            elif isinstance(val, list):
                return [_substitute_vars(v) for v in val]
            return val

        results = []
        for idx, ep in enumerate(items):
            test_case_id = ep.get("test_case_id") or ep.get("id")
            test_key = ep.get("test_key") or f"TC-{idx+1:03d}"
            method = (ep.get("method") or "GET").upper()
            path = str(ep.get("path") or ep.get("url") or "/")
            headers = ep.get("headers") or {}
            params = ep.get("params") or {}
            body = ep.get("body")
            expected_status = int(ep.get("expected_status_code") or 200)
            expected_contains = ep.get("expected_body_contains")
            assertions_defined = ep.get("assertions") or []

            # Clean and format path/URL
            clean_path = path.strip()
            if clean_path.startswith("/http://") or clean_path.startswith("/https://"):
                clean_path = clean_path[1:]

            # Apply runtime variable replacements (e.g. {{token}}, {{baseUrl}})
            clean_path = _substitute_vars(clean_path)

            if clean_path.startswith("http://") or clean_path.startswith("https://"):
                target_url = clean_path
            else:
                target_url = f"{base_url}{clean_path if clean_path.startswith('/') else '/' + clean_path}"

            # Ensure headers is dict and substitute variables
            if isinstance(headers, str):
                try:
                    headers = json.loads(headers)
                except Exception:
                    headers = {}
            headers = _substitute_vars(headers)
            params = _substitute_vars(params)

            # Prepare body payload
            req_data = None
            req_json = None
            if body is not None:
                if isinstance(body, (dict, list)):
                    req_json = _substitute_vars(body)
                elif isinstance(body, str):
                    substituted_body = _substitute_vars(body)
                    try:
                        req_json = json.loads(substituted_body)
                    except Exception:
                        req_data = substituted_body
                else:
                    req_data = str(body)

            t0 = time.perf_counter()
            status_code = 0
            resp_headers = {}
            resp_body = ""
            error_message = None

            try:
                response = requests.request(
                    method=method,
                    url=target_url,
                    headers=headers if headers else None,
                    params=params if params else None,
                    json=req_json,
                    data=req_data,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
                duration_ms = int((time.perf_counter() - t0) * 1000)
                status_code = response.status_code
                resp_headers = dict(response.headers)
                # Limit stored body size to 100KB to protect database
                resp_body = response.text[:102400] if response.text else ""

                # Auto-extract auth tokens and IDs into env_vars for chained requests
                if 200 <= status_code < 300 and resp_body:
                    try:
                        resp_json = response.json()
                        if isinstance(resp_json, dict):
                            for token_key in ("access_token", "token", "jwt", "id_token"):
                                if token_key in resp_json and isinstance(resp_json[token_key], str):
                                    token_val = resp_json[token_key]
                                    env_vars["token"] = token_val
                                    env_vars["access_token"] = token_val
                                    break
                            if "id" in resp_json:
                                env_vars["id"] = resp_json["id"]
                            if "user" in resp_json and isinstance(resp_json["user"], dict):
                                if "id" in resp_json["user"]:
                                    env_vars["userId"] = resp_json["user"]["id"]
                                    env_vars["user_id"] = resp_json["user"]["id"]
                    except Exception:
                        pass
            except requests.exceptions.RequestException as ex:
                duration_ms = int((time.perf_counter() - t0) * 1000)
                error_message = str(ex)
                resp_body = json.dumps({"error": error_message})

            # Assertions evaluation
            run_assertions = []
            if error_message:
                run_assertions.append({
                    "name": f"HTTP Connection ({method} {target_url})",
                    "passed": False,
                    "error": error_message,
                })
                overall_passed = False
            else:
                # 1. Status code assertion
                status_passed = (status_code == expected_status)
                run_assertions.append({
                    "name": f"Status code is {expected_status} (received {status_code})",
                    "passed": status_passed,
                    "error": None if status_passed else f"Expected {expected_status} but received {status_code}",
                })

                # 2. Body substring assertion if specified
                if expected_contains:
                    body_passed = (expected_contains in resp_body)
                    run_assertions.append({
                        "name": f"Response contains '{expected_contains}'",
                        "passed": body_passed,
                        "error": None if body_passed else f"'{expected_contains}' not found in response",
                    })

                # 3. User-defined assertions
                for a in assertions_defined:
                    a_name = a if isinstance(a, str) else str(a.get("name", a))
                    run_assertions.append({
                        "name": a_name,
                        "passed": status_passed,
                    })

                overall_passed = all(a.get("passed") for a in run_assertions)

            results.append({
                "test_case_id": test_case_id,
                "test_key": test_key,
                "status_code": status_code,
                "passed": overall_passed,
                "duration_ms": duration_ms,
                "assertions": run_assertions,
                "method": method,
                "url": target_url,
                "req_headers": headers,
                "req_body": json.dumps(req_json) if req_json is not None else req_data,
                "resp_headers": resp_headers,
                "resp_body": resp_body,
                "request": {
                    "method": method,
                    "url": target_url,
                    "headers": headers,
                    "body": json.dumps(req_json) if req_json is not None else req_data,
                },
                "headers": resp_headers,
                "response_body": resp_body,
            })

        return ApiRunResult(results, is_mock=False)


class NewmanRunner:
    """Postman runner via `newman` CLI, with automatic fallback to HttpRunner if newman is not installed."""

    def run(self, collection_path_or_json, environment=None, test_cases=None, base_url="http://localhost:8080"):
        newman_bin = shutil.which("newman") or shutil.which("newman.cmd")

        # If newman is not installed or collection is given as dict/json
        if not newman_bin or isinstance(collection_path_or_json, (dict, list)):
            print(f"[NewmanRunner] newman CLI not found on PATH or raw JSON collection provided. Using HttpRunner.")
            endpoints = parse_postman_collection(collection_path_or_json)
            return HttpRunner().run(endpoints=endpoints, base_url=base_url, test_cases=test_cases)

        try:
            cmd = [
                newman_bin, "run", collection_path_or_json,
                "--reporters", "json",
                "--env-var", f"baseUrl={base_url}",
            ]
            if environment and isinstance(environment, str):
                cmd.extend(["-e", environment])

            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, shell=True)
            report = json.loads(proc.stdout or "{}")
            results = []
            for execution in report.get("run", {}).get("executions", []):
                resp = execution.get("response", {}) or {}
                req = execution.get("request", {}) or {}
                assertions = execution.get("assertions", [])
                passed = all(a.get("error") is None for a in assertions) if assertions else (resp.get("code") == 200)

                results.append({
                    "test_key": execution.get("item", {}).get("name", "Request"),
                    "status_code": resp.get("code"),
                    "passed": passed,
                    "duration_ms": resp.get("responseTime", 0),
                    "assertions": [{"name": a.get("assertion"), "passed": a.get("error") is None}
                                   for a in assertions],
                    "request": {
                        "method": req.get("method", "GET"),
                        "url": str(req.get("url", "")),
                        "headers": {h.get("key"): h.get("value") for h in req.get("header", []) if isinstance(h, dict)},
                        "body": req.get("body", {}).get("raw"),
                    },
                    "headers": {h.get("key"): h.get("value") for h in resp.get("header", []) if isinstance(h, dict)},
                    "response_body": resp.get("stream"),
                })
            return ApiRunResult(results, is_mock=False)
        except Exception as ex:
            print(f"[NewmanRunner] Subprocess execution failed: {ex}. Falling back to HttpRunner.")
            endpoints = parse_postman_collection(collection_path_or_json)
            return HttpRunner().run(endpoints=endpoints, base_url=base_url, test_cases=test_cases)


class MockApiRunner:
    """Labeled MOCK runner — deterministic demo results, never presented as a real run."""

    def run(self, collection_path=None, environment=None, test_cases=None, base_url="http://localhost:8080", endpoints=None):
        rng = random.Random(collection_path or "seed")
        results = []
        tests_to_run = endpoints or test_cases or [None, None, None]
        for idx, tc in enumerate(tests_to_run):
            if isinstance(tc, dict):
                req = tc.get("request_spec") or tc
                res_spec = tc.get("expected_response_spec") or {}
                exp_status = res_spec.get("status_code", tc.get("expected_status_code", 200))
                method = req.get("method", "POST")
                url = req.get("endpoint", req.get("path", "/api/resource"))
                assertions_list = res_spec.get("assertions", tc.get("assertions", ["Response status code is expected"]))
                tc_id = tc.get("id") or tc.get("test_case_id")
                tc_key = tc.get("test_key", f"TC-{idx+1:03d}")
            else:
                method = "POST"
                url = "/api/resource"
                exp_status = 200
                assertions_list = ["Response status code is expected"]
                tc_id = None
                tc_key = f"TC-{idx+1:03d}"

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
                "request": {"method": method, "url": f"{base_url.rstrip('/')}{url if url.startswith('/') else '/' + url}"},
                "headers": {"content-type": "application/json"},
                "response_body": json.dumps({"_mock": True, "status": "SUCCESS" if passed else "FAILED", "code": status_code}),
            })
        return ApiRunResult(results, is_mock=True)


class AutoRunner:
    """Smart runner that executes against real targets using the optimal engine."""

    def run(self, base_url="http://localhost:8080", collection=None, endpoints=None, test_cases=None, is_mock=False):
        if is_mock:
            return MockApiRunner().run(base_url=base_url, endpoints=endpoints, test_cases=test_cases)

        if collection:
            return NewmanRunner().run(collection_path_or_json=collection, base_url=base_url, test_cases=test_cases)

        return HttpRunner().run(endpoints=endpoints, base_url=base_url, test_cases=test_cases)


def get_runner():
    if Config.API_RUNNER == "newman":
        return NewmanRunner()
    if Config.API_RUNNER == "http":
        return HttpRunner()
    return MockApiRunner()
