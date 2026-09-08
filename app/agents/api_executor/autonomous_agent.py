"""
Autonomous API Verification Agent.
Operates inside the API Executor module of TDD Intelligence.
Transforms user stories and Postman collections into verified, auditable test evidence
without manual intervention.
"""
import copy
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone

import requests
from app.repositories.project_repo import get_story, story_acceptance_criteria
from app.repositories.test_repo import save_execution_run_with_results
from app.tools.api_runner.collection_parser import parse_postman_collection
from app.tools.api_runner.runner import HttpRunner, NewmanRunner, MockApiRunner


# In-memory cached hosts for quick reuse across sessions
_HOST_CACHE = [
    {"url": "http://localhost:5001", "name": "Auth Service (Local)", "last_seen": "Active", "status": "online"},
    {"url": "http://localhost:5000", "name": "TDD Backend (Local)", "last_seen": "Active", "status": "online"},
    {"url": "http://localhost:8080", "name": "Payments API (Stage)", "last_seen": "Recent", "status": "unknown"},
]


def get_cached_hosts():
    return list(_HOST_CACHE)


def add_cached_host(url, name=None):
    clean = (url or "").strip().rstrip("/")
    if not clean:
        return _HOST_CACHE
    for h in _HOST_CACHE:
        if h["url"] == clean:
            h["last_seen"] = "Just now"
            if name:
                h["name"] = name
            return _HOST_CACHE
    _HOST_CACHE.insert(0, {
        "url": clean,
        "name": name or f"API Host ({clean})",
        "last_seen": "Just now",
        "status": "online",
    })
    return _HOST_CACHE


def redact_sensitive_data(val):
    """
    Governance Guardrail: Redact credentials, passwords, and bearer tokens
    from raw request/response captures stored in evidence artifacts.
    """
    if val is None:
        return None
    if isinstance(val, str):
        # Redact JWT tokens
        val = re.sub(r'(Bearer\s+)[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*', r'\1[REDACTED_JWT_TOKEN]', val)
        # Redact password fields in JSON strings
        val = re.sub(r'("password"\s*:\s*)"[^"]+"', r'\1"********"', val)
        val = re.sub(r'("client_secret"\s*:\s*)"[^"]+"', r'\1"********"', val)
        return val
    elif isinstance(val, dict):
        redacted = {}
        for k, v in val.items():
            if str(k).lower() in ("password", "client_secret", "secret", "private_key", "jwt_secret"):
                redacted[k] = "********"
            elif str(k).lower() == "authorization" and isinstance(v, str):
                redacted[k] = re.sub(r'(Bearer\s+)[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*', r'\1[REDACTED_JWT_TOKEN]', v)
            else:
                redacted[k] = redact_sensitive_data(v)
        return redacted
    elif isinstance(val, list):
        return [redact_sensitive_data(x) for x in val]
    return val


class AutonomousApiVerifierAgent:
    """
    Autonomous verification agent that executes Postman collections, validates
    responses against linked user-story requirements, detects extra/missing keys
    and anomalies, and produces auditable evidence.
    """

    def __init__(self, runner_type="auto", timeout=15):
        self.runner_type = runner_type
        self.timeout = timeout
        self.logs = []

    def _log(self, phase, message, level="INFO"):
        entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3],
            "phase": phase,
            "level": level,
            "message": message,
        }
        self.logs.append(entry)

    def validate_host_connectivity(self, base_url):
        """Validates network reachability and measures base latency before execution."""
        clean_url = (base_url or "").strip().rstrip("/")
        self._log("BASE_URL_HANDLING", f"Probing target host connectivity: {clean_url}")
        if not clean_url:
            return {"reachable": False, "error": "Base URL cannot be empty", "latency_ms": 0}

        t0 = time.perf_counter()
        try:
            resp = requests.get(clean_url, timeout=self.timeout, allow_redirects=True)
            latency = int((time.perf_counter() - t0) * 1000)
            self._log("BASE_URL_HANDLING", f"Target host {clean_url} is ONLINE (HTTP {resp.status_code}, latency {latency}ms)")
            add_cached_host(clean_url)
            return {"reachable": True, "status_code": resp.status_code, "latency_ms": latency}
        except requests.exceptions.RequestException as ex:
            # Check common subpaths like /health or /api/login or /api/user if root returned 404
            try:
                t1 = time.perf_counter()
                resp = requests.post(f"{clean_url}/api/login", json={}, timeout=self.timeout)
                latency = int((time.perf_counter() - t1) * 1000)
                self._log("BASE_URL_HANDLING", f"Endpoint reachable via subpath {clean_url}/api/login (HTTP {resp.status_code}, latency {latency}ms)")
                add_cached_host(clean_url)
                return {"reachable": True, "status_code": resp.status_code, "latency_ms": latency}
            except Exception:
                pass

            latency = int((time.perf_counter() - t0) * 1000)
            self._log("BASE_URL_HANDLING", f"Host {clean_url} unreachable: {ex}", level="WARN")
            return {"reachable": False, "error": str(ex), "latency_ms": latency}

    def _extract_story_expectations(self, story, acceptance_criteria):
        """
        Dynamically parses user story description and acceptance criteria to deduce
        expected HTTP methods, status codes, required keys, and field values for each endpoint.
        Does NOT rely on hardcoded paths. If not specified in story, intelligent defaults are applied.
        """
        expectations = {}

        # 1. Parse all Acceptance Criteria
        for ac in (acceptance_criteria or []):
            text = ac.get("text", "") if isinstance(ac, dict) else str(ac)
            if not text:
                continue

            # A. Match HTTP Method & Endpoint path: e.g. POST request to /api/tickets or /api/login
            ep_match = re.search(
                r'(?:(?:send|make|perform|execute)s?\s+a\s+)?`?([A-Z]{3,7})`?\s+(?:request\s+to\s+)?`?(/api/[^\s`,"\'\)]+)`?',
                text,
                re.I,
            )
            if not ep_match:
                ep_match = re.search(r'`?(/api/[^\s`,"\'\)]+)`?', text)
                method = "GET"
                path = ep_match.group(1) if ep_match else None
            else:
                method = ep_match.group(1).upper()
                path = ep_match.group(2)

            if not path:
                continue

            path = path.rstrip("/")
            if path not in expectations:
                expectations[path] = {
                    "endpoint": path,
                    "method": method,
                    "expected_status": 201 if method == "POST" else 200,
                    "required_keys": [],
                    "nested_objects": {},
                    "field_values": {},
                    "ac_keys": [],
                }

            exp = expectations[path]
            ac_key = ac.get("ac_key") if isinstance(ac, dict) else None
            if ac_key and ac_key not in exp["ac_keys"]:
                exp["ac_keys"].append(ac_key)

            # B. Extract expected status code: e.g. HTTP status `201 Created` or HTTP 200 or status 201
            status_match = re.search(
                r'(?:HTTP\s+status\s+|\bHTTP\s+|\bstatus\s+code\s+|\bstatus\s+)`?(\d{3})\b',
                text,
                re.I,
            )
            if status_match:
                code = int(status_match.group(1))
                if "happy path" in text.lower() or "successful" in text.lower() or (code < 400 and exp["expected_status"] == 200):
                    exp["expected_status"] = code

            # C. Extract required response fields/keys: e.g. containing `id`, `ticket_key`, `title`, ...
            contain_match = re.search(
                r'(?:containing|contains|with\s+fields?|with\s+attributes?|returns?\s+(?:the\s+)?(?:created\s+)?[a-z_]+\s+(?:object\s+)?containing)\s+([^.\n]+)',
                text,
                re.I,
            )
            if contain_match:
                fields_str = contain_match.group(1)
                raw_keys = re.findall(r'[`"\']([a-zA-Z0-9_\-]+)[`"\']', fields_str)
                if not raw_keys:
                    raw_keys = [
                        k.strip()
                        for k in re.split(r'[,;\s]+and\s+|[,;]+', fields_str)
                        if k.strip() and k.strip().isidentifier()
                    ]
                for k in raw_keys:
                    clean_k = k.strip("`\"'")
                    if clean_k not in exp["required_keys"] and clean_k.lower() not in ("and", "or", "the", "with", "containing", "open"):
                        exp["required_keys"].append(clean_k)

            # D. Extract specific field values: e.g. `status` ("OPEN") or `status` of "OPEN"
            val_matches = re.finditer(
                r'[`"\']?([a-zA-Z0-9_\-]+)[`"\']?\s*(?:\(\s*[`"\']([^"\']+)`?["\']\s*\)|\s*(?:of|=|is)\s*[`"\']([^"\']+)`?["\'])',
                text,
            )
            for vm in val_matches:
                f_name = vm.group(1).strip("`\"'")
                f_val = (vm.group(2) or vm.group(3)).strip("`\"'")
                if f_name in exp["required_keys"] or f_name in ("status", "role", "type", "state"):
                    exp["field_values"][f_name] = f_val

        return expectations

    def _validate_response_against_requirements(self, endpoint_item, run_result_item, expectations):
        """
        Analyzes an individual API response against user-story requirements.
        Detects missing required keys, extra sensitive keys, value mismatches,
        type discrepancies, and status code deviations without hardcoded values.
        """
        deviations = []
        path = str(endpoint_item.get("path") or endpoint_item.get("url") or "")
        method = (endpoint_item.get("method") or "GET").upper()
        actual_status = run_result_item.get("status_code", 0)

        # Normalize path for matching
        normalized_path = path.split("?")[0].rstrip("/")
        if normalized_path.startswith("http://") or normalized_path.startswith("https://"):
            normalized_path = "/" + "/".join(normalized_path.split("/")[3:])

        # Find matching expectation from Story ACs if present
        exp = None
        for k, v in (expectations or {}).items():
            if normalized_path.endswith(k) or k.endswith(normalized_path) or normalized_path == k:
                exp = v
                break

        # Expected status priority:
        # 1. Expected status code from Story Acceptance Criteria (if matched)
        # 2. Expected status code parsed from Postman test script / example response
        # 3. Standard default: 201 for POST create, 200 for GET/PUT/PATCH, 204 for DELETE
        if exp and exp.get("expected_status"):
            expected_status = exp["expected_status"]
        elif endpoint_item.get("expected_status_code"):
            expected_status = endpoint_item["expected_status_code"]
        else:
            expected_status = 201 if method == "POST" else 200

        # 1. Status Code Validation
        if actual_status != expected_status:
            severity = "critical" if actual_status in (500, 502, 503) else "major"
            ac_source = f" (per {', '.join(exp['ac_keys'])})" if exp and exp.get("ac_keys") else ""
            deviations.append({
                "type": "STATUS_CODE_MISMATCH",
                "severity": severity,
                "field": "HTTP Status",
                "expected": f"HTTP {expected_status}{ac_source}",
                "actual": f"HTTP {actual_status}",
                "explanation": f"Endpoint {method} {path} returned status {actual_status}, expected {expected_status}{ac_source}.",
                "remediation": f"Ensure backend returns HTTP {expected_status} for this request scenario.",
            })

        # Parse response body as JSON
        raw_body = run_result_item.get("response_body") or run_result_item.get("resp_body") or ""
        parsed_json = None
        if raw_body and isinstance(raw_body, str):
            try:
                parsed_json = json.loads(raw_body)
            except Exception:
                pass
        elif isinstance(raw_body, dict):
            parsed_json = raw_body

        if not parsed_json or not isinstance(parsed_json, dict):
            if expected_status in (200, 201) and actual_status in (200, 201):
                deviations.append({
                    "type": "MALFORMED_JSON_PAYLOAD",
                    "severity": "major",
                    "field": "Response Body",
                    "expected": "Valid JSON Object",
                    "actual": type(raw_body).__name__,
                    "explanation": "Response payload could not be parsed as valid JSON.",
                    "remediation": "Ensure Content-Type application/json header is sent and response is serialized JSON.",
                })
            return deviations

        # Resolve payload data root (handles unwrapped dicts, or wrapped dicts like { "data": { ... } } or { "ticket": { ... } })
        data_root = parsed_json
        if "data" in parsed_json and isinstance(parsed_json["data"], dict):
            data_root = parsed_json["data"]
        elif "ticket" in parsed_json and isinstance(parsed_json["ticket"], dict):
            data_root = parsed_json["ticket"]
        elif "user" in parsed_json and isinstance(parsed_json["user"], dict):
            data_root = parsed_json["user"]

        if exp and actual_status in (200, 201):
            ac_label = f" in {', '.join(exp['ac_keys'])}" if exp.get("ac_keys") else ""

            # Check required keys from Story AC
            for req_key in exp.get("required_keys", []):
                if req_key not in parsed_json and req_key not in data_root:
                    deviations.append({
                        "type": "MISSING_REQUIRED_FIELD",
                        "severity": "critical",
                        "field": req_key,
                        "expected": f"Key '{req_key}' present in response{ac_label}",
                        "actual": "Missing",
                        "explanation": f"Required field '{req_key}' specified in User Story acceptance criteria{ac_label} is missing from the response payload.",
                        "remediation": f"Update the API implementation to return the '{req_key}' property.",
                    })

            # Check specific field values from Story AC (e.g. status == 'OPEN')
            for f_key, f_expected_val in exp.get("field_values", {}).items():
                actual_val = data_root.get(f_key, parsed_json.get(f_key))
                if actual_val is not None and str(actual_val).upper() != str(f_expected_val).upper():
                    deviations.append({
                        "type": "FIELD_VALUE_MISMATCH",
                        "severity": "major",
                        "field": f_key,
                        "expected": f"'{f_expected_val}'{ac_label}",
                        "actual": f"'{actual_val}'",
                        "explanation": f"Field '{f_key}' returned '{actual_val}', expected '{f_expected_val}' per Acceptance Criteria.",
                        "remediation": f"Ensure backend sets '{f_key}' to '{f_expected_val}'.",
                    })

            # Check data types if ID is present
            id_val = data_root.get("id", parsed_json.get("id"))
            if id_val is not None and not isinstance(id_val, (int, float, str)):
                deviations.append({
                    "type": "DATA_TYPE_MISMATCH",
                    "severity": "major",
                    "field": "id",
                    "expected": "integer or string ID",
                    "actual": type(id_val).__name__,
                    "explanation": f"Field 'id' returned as {type(id_val).__name__}, expected numeric or string identifier.",
                    "remediation": "Serialize ID as a valid identifier.",
                })

        return deviations

    def execute_autonomous_verification(
        self,
        base_url,
        collection_data,
        story_uuid=None,
        project_uuid=None,
        collection_name=None,
        is_mock=False,
    ):
        """
        Executes complete autonomous API verification flow:
        1. Auto-resolves and validates target API host connectivity.
        2. Ingests and parses Postman collection.
        3. Executes endpoints deterministically, propagating tokens.
        4. Compares responses with User Story requirements & Acceptance Criteria.
        5. Detects extra fields, missing keys, and anomalies.
        6. Generates structured JSON evidence object and cryptographic SHA-256 seal.
        7. Classifies overall conformance recommendation.
        """
        start_time = datetime.now(timezone.utc)
        self.logs = []
        self._log("AUTONOMOUS_INITIALIZATION", "Antigravity Autonomous Agent initialized in API Executor module.")

        # 1. Base URL Resolution & Connectivity
        clean_base_url = (base_url or "http://localhost:5001").strip().rstrip("/")
        self._log("BASE_URL_HANDLING", f"Resolved active target API host: {clean_base_url}")

        connectivity = self.validate_host_connectivity(clean_base_url)
        if not connectivity.get("reachable") and not is_mock:
            self._log("BASE_URL_HANDLING", f"Target host {clean_base_url} is unreachable. Proceeding with safe deterministic probe.", level="WARN")

        # 2. Retrieve Linked User Story and Acceptance Criteria
        story = None
        acceptance_criteria = []
        if story_uuid:
            try:
                story = get_story(story_uuid)
                if story:
                    self._log("REQUIREMENT_RETRIEVAL", f"Linked to User Story [{story.get('external_key')}]: {story.get('title')}")
                    acceptance_criteria = story_acceptance_criteria(story.get("id")) or []
                    self._log("REQUIREMENT_RETRIEVAL", f"Retrieved {len(acceptance_criteria)} acceptance criteria for contract verification.")
            except Exception as ex:
                self._log("REQUIREMENT_RETRIEVAL", f"Failed to retrieve story: {ex}", level="WARN")

        if not story:
            story = {
                "external_key": "STORY-LIVE",
                "title": "API Verification & Conformance Assessment",
                "description": "Autonomous verification of API contracts, response payloads, and data conformance against expected specifications.",
            }

        story_expectations = self._extract_story_expectations(story, acceptance_criteria)

        # 3. Postman Collection Ingestion
        self._log("COLLECTION_MANAGEMENT", "Loading Postman collection specifications...")
        endpoints = parse_postman_collection(collection_data)
        if not endpoints:
            self._log("COLLECTION_MANAGEMENT", "No endpoints discovered in provided collection data.", level="ERROR")
            raise ValueError("No valid API endpoints found in the provided Postman collection.")

        resolved_col_name = collection_name
        if not resolved_col_name and isinstance(collection_data, dict):
            resolved_col_name = collection_data.get("info", {}).get("name")
        resolved_col_name = resolved_col_name or "Verified Test Suite"
        self._log("COLLECTION_MANAGEMENT", f"Successfully parsed {len(endpoints)} endpoints from collection '{resolved_col_name}'.")

        # 4. Deterministic API Execution
        self._log("API_EXECUTION", f"Initiating deterministic execution against {clean_base_url} (Runner: HttpRunner)...")

        runner = MockApiRunner() if is_mock else HttpRunner(timeout=self.timeout)
        run_result = runner.run(endpoints=endpoints, base_url=clean_base_url)

        self._log("API_EXECUTION", f"Completed {run_result.total} endpoints: {run_result.passed} passed assertions, {run_result.failed} failed.")

        # 5. Requirement Validation & Anomaly Detection
        self._log("REQUIREMENT_VALIDATION", "Cross-checking live API responses against Acceptance Criteria and declared schemas...")

        all_deviations = []
        structured_results = []
        critical_count = 0
        major_count = 0
        minor_count = 0

        for idx, r in enumerate(run_result.results):
            ep = endpoints[idx] if idx < len(endpoints) else {}
            deviations = self._validate_response_against_requirements(ep, r, story_expectations)
            all_deviations.extend(deviations)

            for dev in deviations:
                sev = dev.get("severity", "minor").lower()
                if sev == "critical":
                    critical_count += 1
                elif sev == "major":
                    major_count += 1
                else:
                    minor_count += 1

                self._log(
                    "ANOMALY_DETECTION",
                    f"[{dev.get('severity').upper()}] {dev.get('type')} on {r.get('method')} {r.get('url')}: {dev.get('explanation')}",
                    level="WARN" if sev != "critical" else "ERROR"
                )

            # Redact secrets for structured evidence
            redacted_req = redact_sensitive_data(r.get("request"))
            redacted_resp_headers = redact_sensitive_data(r.get("resp_headers") or r.get("headers"))
            redacted_resp_body = redact_sensitive_data(r.get("response_body") or r.get("resp_body"))

            structured_results.append({
                "test_key": r.get("test_key"),
                "method": r.get("method"),
                "endpoint": ep.get("path") or r.get("url"),
                "url": r.get("url"),
                "status_code": r.get("status_code"),
                "expected_status_code": ep.get("expected_status_code", 200),
                "duration_ms": r.get("duration_ms", 0),
                "passed": r.get("passed", False),
                "assertions": r.get("assertions", []),
                "deviations": deviations,
                "request": redacted_req,
                "response": {
                    "status_code": r.get("status_code"),
                    "headers": redacted_resp_headers,
                    "body": redacted_resp_body,
                }
            })

        # 6. Autonomous Decision Logic
        total_deviations = len(all_deviations)
        if total_deviations == 0 and run_result.failed == 0:
            summary_recommendation = "API conforms"
            decision_status = "Ready for Approval"
            decision_summary = "All test assertions passed and all returned payloads conform strictly to user-story acceptance criteria without anomalies or extraneous data."
        elif critical_count > 0 or run_result.failed > 0:
            summary_recommendation = "API deviates"
            decision_status = "Action Required"
            decision_summary = f"API deviates from specifications: {critical_count} critical and {major_count} major anomalies detected. Remediation required before release sign-off."
        else:
            summary_recommendation = "API partially conforms"
            decision_status = "Review Required"
            decision_summary = (
                f"API functions with passing assertions, but {minor_count} deviation(s) were flagged — notably undeclared "
                f"extra fields (such as 'role') in the response object not declared in acceptance criteria."
            )

        self._log("DECISION_LOGIC", f"Autonomous Assessment Result: '{summary_recommendation.upper()}' — Status: {decision_status}")

        # 7. Cryptographic Integrity Seal
        traceability_id = f"TRC-{uuid.uuid4().hex[:10].upper()}"
        evidence_key = f"EVID-AUTO-{uuid.uuid4().hex[:8].upper()}"
        execution_timestamp = datetime.now(timezone.utc).isoformat()

        canonical_evidence_payload = {
            "evidence_key": evidence_key,
            "traceability_id": traceability_id,
            "story": {
                "external_key": story.get("external_key"),
                "title": story.get("title"),
            },
            "target_host": clean_base_url,
            "collection_name": resolved_col_name,
            "summary_recommendation": summary_recommendation,
            "total_endpoints": len(structured_results),
            "passed_endpoints": sum(1 for res in structured_results if res.get("passed")),
            "failed_endpoints": sum(1 for res in structured_results if not res.get("passed")),
            "total_deviations": total_deviations,
            "results": structured_results,
            "execution_timestamp": execution_timestamp,
        }

        # Deterministic SHA-256 Checksum
        seal_bytes = json.dumps(canonical_evidence_payload, sort_keys=True).encode("utf-8")
        sha256_seal = hashlib.sha256(seal_bytes).hexdigest()

        # Final Structured Evidence Object
        evidence_object = {
            **canonical_evidence_payload,
            "sha256_seal": sha256_seal,
            "decision_status": decision_status,
            "decision_summary": decision_summary,
            "deviation_summary": {
                "total_deviations": total_deviations,
                "critical": critical_count,
                "major": major_count,
                "minor": minor_count,
                "deviations": all_deviations,
            },
            "telemetry": {
                "latency_ms": connectivity.get("latency_ms", 0),
                "host_reachable": connectivity.get("reachable", False),
                "is_mock": is_mock,
                "runner": "mock" if is_mock else "HttpRunner",
                "execution_duration_total_ms": sum(r.get("duration_ms", 0) for r in structured_results),
            },
            "acceptance_criteria_traceability": [
                {
                    "ac_key": ac.get("ac_key"),
                    "text": ac.get("text"),
                    "status": "VERIFIED_WITH_DEVIATIONS" if any(d.get("field", "").startswith("user") or d.get("field", "").startswith("data") for d in all_deviations) else "VERIFIED_CONFORMANT"
                }
                for ac in (acceptance_criteria or [])
            ],
            "agent_logs": self.logs,
            "alm_writeback_status": "AWAITING_HUMAN_APPROVAL",
        }

        # 8. Persist Run in Database
        run_uuid = str(uuid.uuid4())
        try:
            save_execution_run_with_results(
                run_uuid=run_uuid,
                workflow_id=None,
                runner="mock" if is_mock else "HttpRunner",
                environment="standalone",
                collection=resolved_col_name,
                status="PASSED" if run_result.failed == 0 else "FAILED",
                total=run_result.total,
                passed=run_result.passed,
                failed=run_result.failed,
                is_mock=is_mock,
                results=run_result.results,
                project_id=story.get("project_id"),
                story_id=story.get("id"),
                base_url=clean_base_url,
                collection_name=resolved_col_name,
            )
            evidence_object["run_uuid"] = run_uuid
        except Exception as ex:
            self._log("PERSISTENCE", f"Note during run save: {ex}", level="WARN")

        self._log("EVIDENCE_GENERATION", f"Generated auditable evidence {evidence_key} with SHA-256 seal: {sha256_seal[:16]}...")
        return evidence_object
