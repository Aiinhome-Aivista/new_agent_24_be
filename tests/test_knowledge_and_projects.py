"""Tests for project creation, story input, knowledge upload, RAG isolation, and contract parsing."""
import uuid
import pytest


@pytest.fixture
def auth_headers(client):
    r = client.post("/api/v1/login", json={"email": "admin@tdd.local", "password": "Passw0rd!"})
    token = r.get_json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_project_and_isolation(client, auth_headers):
    key_a = f"A{uuid.uuid4().hex[:4].upper()}"
    key_b = f"B{uuid.uuid4().hex[:4].upper()}"

    # Create Project Alpha
    r_a = client.post("/api/v1/projects", json={
        "key_code": key_a,
        "name": f"Project {key_a}",
        "description": "Alpha service",
        "target_language": "python",
        "target_framework": "pytest"
    }, headers=auth_headers)
    assert r_a.status_code == 201
    uuid_a = r_a.get_json()["data"]["uuid"]

    # Create Project Beta
    r_b = client.post("/api/v1/projects", json={
        "key_code": key_b,
        "name": f"Project {key_b}",
        "description": "Beta service",
        "target_language": "java",
        "target_framework": "junit5"
    }, headers=auth_headers)
    assert r_b.status_code == 201
    uuid_b = r_b.get_json()["data"]["uuid"]

    # Upload Knowledge to Alpha
    r_up_a = client.post(f"/api/v1/projects/{uuid_a}/knowledge", json={
        "title": "alpha_login_rules.txt",
        "content": "Alpha Login Rule: Users must authenticate with a 2FA hardware token and company email.",
        "doc_type": "acceptance_criteria"
    }, headers=auth_headers)
    assert r_up_a.status_code == 201
    assert r_up_a.get_json()["data"]["chunk_count"] >= 1

    # Upload Knowledge to Beta
    r_up_b = client.post(f"/api/v1/projects/{uuid_b}/knowledge", json={
        "title": "beta_payment_rules.txt",
        "content": "Beta Payment Rule: Single transactions exceeding 50,000 USD require dual director approval.",
        "doc_type": "coding_standards"
    }, headers=auth_headers)
    assert r_up_b.status_code == 201

    # Test RAG Retrieval for Alpha: Must retrieve Alpha rules, NEVER Beta rules
    rag_a = client.post(f"/api/v1/projects/{uuid_a}/rag/query", json={"query": "hardware token dual director"}, headers=auth_headers)
    assert rag_a.status_code == 200
    chunks_a = rag_a.get_json()["data"]["chunks"]
    assert len(chunks_a) >= 1
    assert "2FA hardware token" in chunks_a[0]["content"]
    assert "dual director approval" not in chunks_a[0]["content"]

    # Test RAG Retrieval for Beta: Must retrieve Beta rules, NEVER Alpha rules
    rag_b = client.post(f"/api/v1/projects/{uuid_b}/rag/query", json={"query": "hardware token dual director"}, headers=auth_headers)
    assert rag_b.status_code == 200
    chunks_b = rag_b.get_json()["data"]["chunks"]
    assert len(chunks_b) >= 1
    assert "dual director approval" in chunks_b[0]["content"]
    assert "2FA hardware token" not in chunks_b[0]["content"]


def test_create_story_with_acceptance_criteria(client, auth_headers):
    # Fetch projects
    p_res = client.get("/api/v1/projects", headers=auth_headers)
    projects = p_res.get_json()["data"]["projects"]
    project_uuid = projects[0]["uuid"]

    story_key = f"TEST-{uuid.uuid4().hex[:3].upper()}"

    # Create story
    story_payload = {
        "project_uuid": project_uuid,
        "external_key": story_key,
        "title": "Test User Login Capability",
        "description": "As a user I want to log in with valid credentials.",
        "acceptance_criteria": [
            {"ac_key": "AC-1", "text": "Valid credentials return JWT access token."},
            {"ac_key": "AC-2", "text": "Invalid password returns 401 UNAUTHORIZED."}
        ]
    }
    r = client.post("/api/v1/stories", json=story_payload, headers=auth_headers)
    assert r.status_code == 201
    data = r.get_json()["data"]
    assert data["external_key"] == story_key
    assert len(data["acceptance_criteria"]) == 2

    # Get story detail
    s_detail = client.get(f"/api/v1/stories/{data['uuid']}", headers=auth_headers)
    assert s_detail.status_code == 200
    assert len(s_detail.get_json()["data"]["acceptance_criteria"]) == 2
