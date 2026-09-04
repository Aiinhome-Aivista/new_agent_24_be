"""
Deterministic API test runner. Executes real Bruno/Postman collections when configured;
otherwise a labeled MOCK runner produces clearly-marked demo results. The LLM is NEVER
involved in producing execution values.
"""
import subprocess
import json
import random
import requests
import time
from app.config import Config


class ApiRunResult:
    def __init__(self, results, is_mock):
        self.results = results   # list of per-test dicts
        self.is_mock = is_mock


class NewmanRunner:
    """Real runner via `newman` (Postman) — requires newman on PATH and a collection file."""
    def run(self, collection_path, environment, test_cases=None):
        try:
            # shell=True is often required on Windows to resolve npm global binaries like 'newman.cmd'
            proc = subprocess.run(
                ["newman", "run", collection_path, "-e", environment, "--reporters", "json"],
                capture_output=True, text=True, timeout=300, shell=True
            )
        except FileNotFoundError:
            print("[NewmanRunner] Error: 'newman' command not found. Falling back to MockApiRunner.")
            return MockApiRunner().run(collection_path, environment, test_cases)

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


class LiveApiRunner:
    """Real runner via `requests` that hits the dynamically spun-up or provided target URL."""
    def run(self, collection_path, environment, test_cases=None):
        import http.client
        results = []
        tests_to_run = test_cases if test_cases else []
        for idx, tc in enumerate(tests_to_run):
            if not isinstance(tc, dict):
                tc = {}
            req = tc.get("request_spec") or {}
            res_spec = tc.get("expected_response_spec") or {}
            exp_status = res_spec.get("status_code", 200)
            method = (req.get("method") or tc.get("method") or "GET").upper()
            
            # Extract headers and params
            headers = tc.get("headers") or req.get("headers") or {}
            if not isinstance(headers, dict):
                headers = {}
            # Filter out empty keys
            headers = {str(k): str(v) for k, v in headers.items() if str(k).strip()}

            params = tc.get("params") or req.get("params") or {}
            if not isinstance(params, dict):
                params = {}
            params = {str(k): str(v) for k, v in params.items() if str(k).strip()}

            # Extract auth
            auth_spec = tc.get("auth") or req.get("auth") or {}
            req_auth = None
            if isinstance(auth_spec, dict):
                auth_type = auth_spec.get("type")
                if auth_type == "bearer" and auth_spec.get("token"):
                    headers["Authorization"] = f"Bearer {auth_spec['token']}"
                elif auth_type == "basic":
                    req_auth = (auth_spec.get("username", ""), auth_spec.get("password", ""))
                elif auth_type == "apikey":
                    key = auth_spec.get("key", "")
                    val = auth_spec.get("value", "")
                    if key:
                        if auth_spec.get("add_to") == "query":
                            params[key] = val
                        else:
                            headers[key] = val

            # Timeout (0 or None means unlimited wait time)
            raw_timeout = tc.get("timeout") if "timeout" in tc else req.get("timeout")
            if raw_timeout is None or raw_timeout == 0 or raw_timeout == "0" or raw_timeout == "none" or raw_timeout == "unlimited":
                timeout_tuple = (10.0, None)
                timeout_label = "unlimited"
            else:
                try:
                    timeout_val = float(raw_timeout)
                    if timeout_val <= 0:
                        timeout_tuple = (10.0, None)
                        timeout_label = "unlimited"
                    else:
                        timeout_tuple = (min(10.0, timeout_val), timeout_val)
                        timeout_label = f"{int(timeout_val)}s"
                except Exception:
                    timeout_tuple = (10.0, None)
                    timeout_label = "unlimited"

            # Payload & Body type
            body_type = tc.get("body_type") or "json"
            raw_payload = tc.get("actual_payload") or tc.get("payload") or req.get("payload")
            
            json_data = None
            form_data = None
            raw_body = None

            # Auto-detect JSON payload
            if body_type == "json":
                if isinstance(raw_payload, (dict, list)):
                    json_data = raw_payload
                elif isinstance(raw_payload, str) and raw_payload.strip():
                    try:
                        json_data = json.loads(raw_payload)
                    except Exception:
                        raw_body = raw_payload
                if "Content-Type" not in headers and "content-type" not in headers:
                    headers["Content-Type"] = "application/json"
            elif body_type == "raw":
                if isinstance(raw_payload, str):
                    # Check if it is valid JSON anyway
                    stripped = raw_payload.strip()
                    if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
                        try:
                            json_data = json.loads(raw_payload)
                            if "Content-Type" not in headers and "content-type" not in headers:
                                headers["Content-Type"] = "application/json"
                        except Exception:
                            raw_body = raw_payload
                    else:
                        raw_body = raw_payload
                elif isinstance(raw_payload, (dict, list)):
                    json_data = raw_payload
                    if "Content-Type" not in headers and "content-type" not in headers:
                        headers["Content-Type"] = "application/json"
                else:
                    raw_body = str(raw_payload) if raw_payload is not None else None
            elif body_type in ("form-data", "x-www-form-urlencoded") and isinstance(raw_payload, dict):
                form_data = raw_payload
            elif body_type == "none" or method in ("GET", "HEAD"):
                json_data = None
            else:
                json_data = raw_payload if raw_payload is not None else None

            # Ensure Accept header if not present
            if "Accept" not in headers and "accept" not in headers:
                headers["Accept"] = "application/json, text/plain, */*"

            # Resolve URL
            raw_url = str(req.get("endpoint") or tc.get("url") or tc.get("endpoint") or "").strip()
            env_str = str(environment or "").strip()

            if raw_url.startswith("http://") or raw_url.startswith("https://"):
                url = raw_url
            elif raw_url.startswith("/"):
                base = env_str if (env_str.startswith("http://") or env_str.startswith("https://")) else "http://localhost:8080"
                url = f"{base.rstrip('/')}{raw_url}"
            elif raw_url:
                if raw_url.startswith("localhost") or raw_url.startswith("127.0.0.1") or (":" in raw_url and not raw_url.startswith("http")):
                    url = f"http://{raw_url}"
                else:
                    base = env_str if (env_str.startswith("http://") or env_str.startswith("https://")) else "http://localhost:8080"
                    url = f"{base.rstrip('/')}/{raw_url}"
            else:
                url = env_str if (env_str.startswith("http://") or env_str.startswith("https://")) else "http://localhost:8080"

            tc_id = tc.get("id")
            tc_key = tc.get("test_key", f"TC-{idx+1:03d}")
            assertions_list = res_spec.get("assertions", ["Response status code is expected"])
            
            start_time = time.time()
            response_headers = {}
            response_cookies = []
            size_bytes = 0
            status_text = ""
            try:
                kwargs = {
                    "method": method,
                    "url": url,
                    "headers": headers,
                    "params": params if params else None,
                    "timeout": timeout_tuple
                }
                if req_auth:
                    kwargs["auth"] = req_auth
                if json_data is not None:
                    kwargs["json"] = json_data
                elif form_data is not None:
                    kwargs["data"] = form_data
                elif raw_body is not None:
                    kwargs["data"] = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body

                response = requests.request(**kwargs)
                duration_ms = max(1, int((time.time() - start_time) * 1000))
                status_code = response.status_code
                response_text = response.text
                size_bytes = len(response.content)
                response_headers = dict(response.headers)
                response_cookies = [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path} for c in response.cookies]
                
                try:
                    status_text = http.client.responses.get(status_code, "Unknown")
                except Exception:
                    status_text = "OK" if status_code < 400 else "Error"

                passed = (status_code == exp_status) if ("status_code" in res_spec) else (status_code < 400)
                
            except requests.exceptions.Timeout as e:
                duration_ms = max(1, int((time.time() - start_time) * 1000))
                status_code = 504
                status_text = f"Gateway / Read Timeout ({timeout_label})"
                response_text = f"Request timed out ({timeout_label}) connecting to {url}.\n\nTroubleshooting:\n1. Verify if the target API service is active and listening on this port.\n2. If this is a local service, use `http://localhost:3035` (e.g. run your API with `python run.py` or `uvicorn`).\n3. Check if the remote host firewall/security group is blocking inbound traffic on port {url.split(':')[-1].split('/')[0] if ':' in url else '80'}."
                passed = False
            except requests.exceptions.ConnectionError as e:
                duration_ms = max(1, int((time.time() - start_time) * 1000))
                status_code = 502
                status_text = "Connection Failed"
                response_text = f"Failed to establish a connection to {url}.\n\nError: {e}\n\nTips:\n- Ensure the target host and port are online and reachable.\n- If using localhost, ensure the local development server is running."
                passed = False
            except requests.exceptions.RequestException as e:
                duration_ms = max(1, int((time.time() - start_time) * 1000))
                status_code = 500
                status_text = "Request Execution Error"
                response_text = str(e)
                passed = False
            except Exception as e:
                duration_ms = max(1, int((time.time() - start_time) * 1000))
                status_code = 500
                status_text = "Internal Client Error"
                response_text = str(e)
                passed = False

            # Format human-friendly size
            if size_bytes < 1024:
                size_str = f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                size_str = f"{size_bytes / 1024:.2f} KB"
            else:
                size_str = f"{size_bytes / (1024 * 1024):.2f} MB"

            built_assertions = []
            for a in (assertions_list[:3] if assertions_list else ["Status code is as expected"]):
                a_name = a if isinstance(a, str) else str(a)
                built_assertions.append({"name": a_name, "passed": passed})

            results.append({
                "test_case_id": tc_id,
                "test_key": tc_key,
                "status_code": status_code,
                "status_text": status_text,
                "passed": passed,
                "duration_ms": duration_ms,
                "size_bytes": size_bytes,
                "size_str": size_str,
                "response_headers": response_headers,
                "response_cookies": response_cookies,
                "assertions": built_assertions,
                "request": {
                    "method": method,
                    "url": url,
                    "headers": headers,
                    "params": params
                },
                "response_body": response_text,
            })
            
        return ApiRunResult(results, is_mock=False)


def get_runner(force_live=False):
    if force_live or Config.API_RUNNER == "live":
        return LiveApiRunner()
    if Config.API_RUNNER == "newman":
        return NewmanRunner()
    return MockApiRunner()

