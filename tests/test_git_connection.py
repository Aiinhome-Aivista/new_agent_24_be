"""Tests for Git repository connection validation tool and endpoints."""
# pyrefly: ignore [missing-import]
import pytest
from app.tools.repository.git_checker import validate_git_connection, parse_github_url


@pytest.fixture
def auth_headers(client):
    r = client.post("/api/v1/login", json={"email": "admin@tdd.local", "password": "Passw0rd!"})
    token = r.get_json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_parse_github_url():
    assert parse_github_url("https://github.com/torvalds/linux") == ("torvalds", "linux")
    assert parse_github_url("https://github.com/torvalds/linux.git") == ("torvalds", "linux")
    assert parse_github_url("git@github.com:torvalds/linux.git") == ("torvalds", "linux")
    assert parse_github_url("https://not-github.com/foo/bar") is None
    assert parse_github_url("") is None


def test_validate_git_connection_invalid_url():
    res = validate_git_connection("")
    assert res["connected"] is False
    assert res["status"] == "INVALID_URL"

    res = validate_git_connection("not_a_url")
    assert res["connected"] is False
    assert res["status"] == "INVALID_URL"


def test_validate_git_connection_public_repo():
    # Public linux kernel repo check
    res = validate_git_connection("https://github.com/torvalds/linux", git_branch="master")
    assert res["connected"] is True
    assert res["status"] == "CONNECTED"
    assert res["repo"] == "torvalds/linux"
    assert res["branch"] == "master"
    assert res["latency_ms"] >= 0


def test_validate_git_connection_nonexistent_branch():
    res = validate_git_connection("https://github.com/torvalds/linux", git_branch="nonexistent_branch_98765")
    assert res["connected"] is False
    assert res["status"] == "BRANCH_NOT_FOUND"
    assert "not found" in res["message"].lower()


def test_validate_git_connection_endpoint_adhoc(client, auth_headers):
    # Test valid repo via API
    resp = client.post("/api/v1/projects/test-git-connection", json={
        "git_repo_url": "https://github.com/torvalds/linux",
        "git_branch": "master",
        "git_provider": "github"
    }, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["data"]["connected"] is True
    assert body["data"]["repo"] == "torvalds/linux"

    # Test invalid URL via API
    resp_invalid = client.post("/api/v1/projects/test-git-connection", json={
        "git_repo_url": "invalid_url_test"
    }, headers=auth_headers)
    assert resp_invalid.status_code == 200
    body_invalid = resp_invalid.get_json()
    assert body_invalid["success"] is True
    assert body_invalid["data"]["connected"] is False
    assert body_invalid["data"]["status"] == "INVALID_URL"
