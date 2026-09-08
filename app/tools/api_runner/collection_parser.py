"""
Collection parser for Postman (v2.0, v2.1) and Bruno collections.
Converts collections into flat lists of endpoint specifications.
"""
import re
import json


def parse_postman_collection(collection_data):
    """
    Parses a Postman collection JSON (dict or string) into a list of normalized endpoint dicts.
    Recursively inspects folders and requests.
    """
    if isinstance(collection_data, str):
        try:
            collection_data = json.loads(collection_data)
        except Exception:
            return []

    if not isinstance(collection_data, dict):
        return []

    endpoints = []
    items = collection_data.get("item", [])

    def _extract_items(item_list, folder_prefix=""):
        for item in item_list:
            if not isinstance(item, dict):
                continue

            name = item.get("name", "Request")
            full_name = f"{folder_prefix} / {name}" if folder_prefix else name

            # If it's a folder, recurse
            if "item" in item and isinstance(item["item"], list):
                _extract_items(item["item"], folder_prefix=full_name)
                continue

            request_data = item.get("request")
            if not request_data:
                continue

            # If request is just a string URL (Postman v1 format)
            if isinstance(request_data, str):
                endpoints.append({
                    "test_key": full_name,
                    "method": "GET",
                    "path": request_data,
                    "headers": {},
                    "body": None,
                    "expected_status_code": 200,
                    "assertions": ["Status code is 200"],
                })
                continue

            method = (request_data.get("method") or "GET").upper()

            # Parse URL
            url_obj = request_data.get("url")
            raw_url = ""
            path = "/"
            query_params = {}

            if isinstance(url_obj, str):
                raw_url = url_obj
            elif isinstance(url_obj, dict):
                raw_url = url_obj.get("raw", "")
                # Extract path segments if raw not descriptive
                if not raw_url and "path" in url_obj:
                    path_parts = url_obj["path"]
                    if isinstance(path_parts, list):
                        path = "/" + "/".join(str(p) for p in path_parts)
                # Extract query parameters
                for q in url_obj.get("query", []):
                    if isinstance(q, dict) and q.get("key"):
                        query_params[q["key"]] = q.get("value", "")

            # Normalize raw_url to relative path by stripping variable placeholders like {{baseUrl}}
            cleaned_url = raw_url
            if cleaned_url:
                # Remove common Postman env placeholders: {{baseUrl}}, {{base_url}}, {{host}}, etc.
                cleaned_url = re.sub(r"\{\{[^}]+\}\}", "", cleaned_url)
                # If it had a full scheme http(s)://..., strip the domain part if baseUrl will be prefixed
                if cleaned_url.startswith("http://") or cleaned_url.startswith("https://"):
                    parts = cleaned_url.split("/", 3)
                    if len(parts) >= 4:
                        cleaned_url = "/" + parts[3]
                    else:
                        cleaned_url = "/"
                path = cleaned_url if cleaned_url.startswith("/") else f"/{cleaned_url}"
            elif not path.startswith("/"):
                path = f"/{path}"

            # Headers
            headers = {}
            header_items = request_data.get("header", [])
            if isinstance(header_items, list):
                for h in header_items:
                    if isinstance(h, dict) and h.get("key") and not h.get("disabled"):
                        headers[h["key"]] = h.get("value", "")
            elif isinstance(header_items, dict):
                headers = header_items

            # Body
            body_content = None
            req_body = request_data.get("body")
            if isinstance(req_body, dict):
                mode = req_body.get("mode")
                if mode == "raw":
                    body_content = req_body.get("raw")
                elif mode == "formdata":
                    fd = {}
                    for param in req_body.get("formdata", []):
                        if isinstance(param, dict) and param.get("key") and not param.get("disabled"):
                            fd[param["key"]] = param.get("value", "")
                    body_content = json.dumps(fd) if fd else None
                elif mode == "urlencoded":
                    ue = {}
                    for param in req_body.get("urlencoded", []):
                        if isinstance(param, dict) and param.get("key") and not param.get("disabled"):
                            ue[param["key"]] = param.get("value", "")
                    body_content = json.dumps(ue) if ue else None

            # Expected status code and response examples
            expected_status = 200
            sample_response = None
            response_examples = []
            responses = item.get("response", [])
            if responses and isinstance(responses, list):
                for resp in responses:
                    if isinstance(resp, dict):
                        resp_code = resp.get("code")
                        resp_body = resp.get("body")
                        resp_name = resp.get("name", "")
                        if resp_body:
                            response_examples.append({
                                "status_code": resp_code,
                                "name": resp_name,
                                "body": resp_body
                            })
                first_resp = responses[0]
                if isinstance(first_resp, dict):
                    if first_resp.get("code"):
                        try:
                            expected_status = int(first_resp["code"])
                        except Exception:
                            pass
                    if first_resp.get("body"):
                        sample_response = first_resp.get("body")

            # Assertions from test scripts if available
            test_assertions = []
            for event in item.get("event", []):
                if isinstance(event, dict) and event.get("listen") == "test":
                    script = event.get("script", {})
                    exec_lines = script.get("exec", [])
                    if isinstance(exec_lines, list):
                        for line in exec_lines:
                            # Extract expected status code from test script if not already set by explicit response example
                            status_code_match = re.search(r'pm\.response\.(?:to\.)?(?:have\.)?status\(\s*(\d{3})\s*\)', line)
                            if not status_code_match:
                                status_code_match = re.search(r'pm\.expect\s*\(\s*pm\.response\.code\s*\)\.to\.(?:eql|equal)\s*\(\s*(\d{3})\s*\)', line)
                            if not status_code_match:
                                status_code_match = re.search(r'Status\s+is\s+(\d{3})', line, re.IGNORECASE)
                            if status_code_match and (not responses or expected_status == 200):
                                try:
                                    expected_status = int(status_code_match.group(1))
                                except Exception:
                                    pass

                            match = re.search(r'pm\.test\(\s*["\']([^"\']+)["\']', line)
                            if match:
                                test_desc = match.group(1)
                                if test_desc not in test_assertions:
                                    test_assertions.append(test_desc)

            assertions = [f"Status code is {expected_status}"] + [a for a in test_assertions if not a.startswith("Status code is")]

            endpoints.append({
                "test_key": full_name,
                "method": method,
                "path": path,
                "headers": headers,
                "params": query_params,
                "body": body_content,
                "sample_request": body_content,
                "sample_response": sample_response,
                "response_example": sample_response,
                "response_examples": response_examples,
                "expected_status_code": expected_status,
                "assertions": assertions,
            })

    _extract_items(items)
    return endpoints
