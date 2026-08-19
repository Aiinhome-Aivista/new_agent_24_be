"""
Git repository connectivity validator.
Validates repository accessibility, authorization, branch existence, and latency.
Supports GitHub REST API, token authentication, and generic Git remotes.
"""
import re
import time
import requests
from typing import Dict, Any, Optional, Tuple
from app.config import Config


def parse_github_url(url: str) -> Optional[Tuple[str, str]]:
    """
    Extracts (owner, repo) from common GitHub URL patterns:
    - https://github.com/owner/repo
    - https://github.com/owner/repo.git
    - git@github.com:owner/repo.git
    """
    if not url:
        return None
    url = url.strip()
    
    # HTTPS pattern
    https_match = re.match(r"^https?://(?:www\.)?github\.com/([^/]+)/([^/.]+)(?:\.git)?/?$", url, re.IGNORECASE)
    if https_match:
        return https_match.group(1), https_match.group(2)
        
    # SSH pattern
    ssh_match = re.match(r"^git@github\.com:([^/]+)/([^/.]+)(?:\.git)?$", url, re.IGNORECASE)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)
        
    return None


def validate_git_connection(
    git_repo_url: Optional[str],
    git_branch: str = "main",
    git_provider: str = "github",
    token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Tests connectivity to a Git repository and verifies if the specified branch exists.
    Returns a structured dictionary with connection status, diagnostic message, and latency.
    """
    if not git_repo_url or not git_repo_url.strip():
        return {
            "connected": False,
            "status": "INVALID_URL",
            "message": "Git repository URL is required.",
            "repo": None,
            "branch": git_branch,
            "latency_ms": 0
        }

    url = git_repo_url.strip()
    branch = (git_branch or "main").strip()
    start_time = time.time()

    # 1. GitHub Provider & GitHub URL Check
    gh_parsed = parse_github_url(url)
    if gh_parsed:
        owner, repo = gh_parsed
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "TDD-Intelligence-Platform/1.0"
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            # Step A: Validate Repository Existence & Access
            repo_api_url = f"https://api.github.com/repos/{owner}/{repo}"
            resp = requests.get(repo_api_url, headers=headers, timeout=6.0)
            latency_ms = int((time.time() - start_time) * 1000)

            if resp.status_code == 200:
                repo_data = resp.json()
                default_branch = repo_data.get("default_branch", "main")
                is_private = repo_data.get("private", False)

                # Step B: Check if target branch exists
                branch_api_url = f"https://api.github.com/repos/{owner}/{repo}/branches/{branch}"
                b_resp = requests.get(branch_api_url, headers=headers, timeout=6.0)
                b_latency_ms = int((time.time() - start_time) * 1000)

                if b_resp.status_code == 200:
                    return {
                        "connected": True,
                        "status": "CONNECTED",
                        "provider": "github",
                        "repo": f"{owner}/{repo}",
                        "branch": branch,
                        "default_branch": default_branch,
                        "is_private": is_private,
                        "message": f"Successfully connected to GitHub repository '{owner}/{repo}' (Branch: '{branch}').",
                        "latency_ms": b_latency_ms
                    }
                elif b_resp.status_code == 404:
                    return {
                        "connected": False,
                        "status": "BRANCH_NOT_FOUND",
                        "provider": "github",
                        "repo": f"{owner}/{repo}",
                        "branch": branch,
                        "default_branch": default_branch,
                        "is_private": is_private,
                        "message": f"Repository '{owner}/{repo}' exists, but branch '{branch}' was not found. (Default branch is '{default_branch}').",
                        "latency_ms": b_latency_ms
                    }
                else:
                    return {
                        "connected": True,
                        "status": "CONNECTED_BRANCH_UNVERIFIED",
                        "provider": "github",
                        "repo": f"{owner}/{repo}",
                        "branch": branch,
                        "default_branch": default_branch,
                        "is_private": is_private,
                        "message": f"Connected to repository '{owner}/{repo}'. Branch verification returned status {b_resp.status_code}.",
                        "latency_ms": b_latency_ms
                    }

            elif resp.status_code == 404:
                return {
                    "connected": False,
                    "status": "NOT_FOUND",
                    "provider": "github",
                    "repo": f"{owner}/{repo}",
                    "branch": branch,
                    "message": f"GitHub repository '{owner}/{repo}' not found. Verify the URL or check if the repository is private.",
                    "latency_ms": latency_ms
                }
            elif resp.status_code in (401, 403):
                msg = resp.json().get("message", "") if resp.headers.get("content-type", "").startswith("application/json") else ""
                rate_limited = "rate limit" in msg.lower()
                status_code = "RATE_LIMITED" if rate_limited else "AUTH_REQUIRED"
                detail = "GitHub API rate limit reached. Please configure a GitHub Token." if rate_limited else "Access denied. If this repository is private, a valid GitHub Access Token is required."
                return {
                    "connected": False,
                    "status": status_code,
                    "provider": "github",
                    "repo": f"{owner}/{repo}",
                    "branch": branch,
                    "message": detail,
                    "latency_ms": latency_ms
                }
            else:
                return {
                    "connected": False,
                    "status": "HTTP_ERROR",
                    "provider": "github",
                    "repo": f"{owner}/{repo}",
                    "branch": branch,
                    "message": f"GitHub returned HTTP {resp.status_code}: {resp.text[:120]}",
                    "latency_ms": latency_ms
                }

        except requests.exceptions.Timeout:
            return {
                "connected": False,
                "status": "TIMEOUT",
                "provider": "github",
                "repo": f"{owner}/{repo}",
                "branch": branch,
                "message": "Connection to GitHub API timed out after 6 seconds.",
                "latency_ms": int((time.time() - start_time) * 1000)
            }
        except requests.exceptions.RequestException as e:
            return {
                "connected": False,
                "status": "NETWORK_ERROR",
                "provider": "github",
                "repo": f"{owner}/{repo}",
                "branch": branch,
                "message": f"Network error communicating with GitHub: {str(e)}",
                "latency_ms": int((time.time() - start_time) * 1000)
            }

    # 2. Generic HTTPS Git repository check
    if url.startswith("http://") or url.startswith("https://"):
        try:
            resp = requests.head(url, timeout=6.0, allow_redirects=True)
            latency_ms = int((time.time() - start_time) * 1000)
            if resp.status_code < 400:
                return {
                    "connected": True,
                    "status": "CONNECTED",
                    "provider": git_provider or "git",
                    "repo": url,
                    "branch": branch,
                    "message": f"Remote Git endpoint is reachable (HTTP {resp.status_code}).",
                    "latency_ms": latency_ms
                }
            else:
                return {
                    "connected": False,
                    "status": "HTTP_ERROR",
                    "provider": git_provider or "git",
                    "repo": url,
                    "branch": branch,
                    "message": f"Remote server returned HTTP {resp.status_code}.",
                    "latency_ms": latency_ms
                }
        except Exception as e:
            return {
                "connected": False,
                "status": "UNREACHABLE",
                "provider": git_provider or "git",
                "repo": url,
                "branch": branch,
                "message": f"Could not reach remote URL: {str(e)}",
                "latency_ms": int((time.time() - start_time) * 1000)
            }

    return {
        "connected": False,
        "status": "INVALID_URL",
        "provider": git_provider or "git",
        "repo": url,
        "branch": branch,
        "message": "Invalid Git repository URL format. Please provide a valid HTTP/HTTPS GitHub or Git repository URL.",
        "latency_ms": 0
    }
