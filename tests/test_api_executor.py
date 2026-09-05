import json
import pytest
from app.auth.security import issue_access
from app.tools.api_runner.collection_parser import parse_postman_collection
from app.tools.api_runner.runner import HttpRunner, AutoRunner, ApiRunResult


@pytest.fixture
def auth_headers():
    token = issue_access(1, ["ADMIN"], ["*"])
    return {"Authorization": f"Bearer {token}"}


def test_parse_postman_collection_structure():
    sample_collection = {
        "info": {
            "name": "Test Payment API",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
        },
        "item": [
            {
                "name": "Authorize Payment",
                "request": {
                    "method": "POST",
                    "header": [
                        {"key": "Content-Type", "value": "application/json"}
                    ],
                    "url": {
                        "raw": "{{baseUrl}}/api/v1/payments/authorize",
                        "path": ["api", "v1", "payments", "authorize"],
                        "query": [{"key": "timeout", "value": "30"}]
                    },
                    "body": {
                        "mode": "raw",
                        "raw": "{\"amount\": 150.00, \"currency\": \"USD\"}"
                    }
                },
                "event": [
                    {
                        "listen": "test",
                        "script": {
                            "exec": [
                                "pm.test('Status code is 200', function () { pm.response.to.have.status(200); });"
                            ]
                        }
                    }
                ]
            }
        ]
    }

    endpoints = parse_postman_collection(sample_collection)
    assert len(endpoints) == 1
    ep = endpoints[0]
    assert ep["test_key"] == "Authorize Payment"
    assert ep["method"] == "POST"
    assert ep["path"] == "/api/v1/payments/authorize"
    assert ep["headers"].get("Content-Type") == "application/json"
    assert "amount" in ep["body"]
    assert "Status code is 200" in ep["assertions"]


def test_http_runner_mock_and_execution():
    runner = HttpRunner()
    endpoints = [
        {
            "test_key": "Health Check",
            "method": "GET",
            "path": "/health",
            "expected_status_code": 200,
        }
    ]
    # Execute against local non-existent port to test safe exception handling without crashing
    res = runner.run(endpoints=endpoints, base_url="http://127.0.0.1:59999")
    assert isinstance(res, ApiRunResult)
    assert res.total == 1
    assert res.failed == 1
    assert len(res.results) == 1
    assert "assertions" in res.results[0]
    assert res.results[0]["status_code"] == 0


def test_api_executor_run_validation(client, auth_headers):
    # Missing base_url
    resp = client.post("/api/v1/api-executor/run", headers=auth_headers, json={})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "VALIDATION_ERROR"

    # Missing endpoints
    resp2 = client.post("/api/v1/api-executor/run", headers=auth_headers, json={"base_url": "http://localhost:8080"})
    assert resp2.status_code == 400
    assert resp2.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_api_executor_parse_collection_endpoint(client, auth_headers):
    sample = {
        "info": {"name": "Orders API"},
        "item": [
            {
                "name": "List Orders",
                "request": {
                    "method": "GET",
                    "url": "http://localhost:8080/api/orders"
                }
            }
        ]
    }
    resp = client.post("/api/v1/api-executor/parse-collection", headers=auth_headers, json=sample)
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["collection_name"] == "Orders API"
    assert data["total"] == 1
    assert data["endpoints"][0]["method"] == "GET"
