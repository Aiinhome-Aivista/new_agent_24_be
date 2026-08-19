"""
Git repository connectivity validator.
Validates repository accessibility, authorization, branch existence, and latency.
Supports GitHub REST API, embedded PAT tokens, token authentication, and Git Smart HTTP remotes.
"""
import re
import time
import requests
from typing import Dict, Any, Optional, Tuple


def parse_github_url(url: str) -> Optional[Tuple[str, str, Optional[str]]]:
    """
    Extracts (owner, repo, embedded_token) from common GitHub URL patterns:
    - https://github.com/owner/repo
    - https://github.com/owner/repo.git
    - https://<token>@github.com/owner/repo.git
    - https://<user>:<token>@github.com/owner/repo.git
    - git@github.com:owner/repo.git

    Returns:
        (owner, repo, embedded_token) or None
    """
    if not url:
        return None
    url = url.strip()

    # HTTPS pattern with optional embedded auth (token or user:token)
    https_match = re.match(
        r"^https?://(?:([^@/:]+)(?::([^@/:]*))?@)?(?:www\.)?github\.com/([^/]+)/([^/.]+?)(?:\.git)?/?$",
        url,
        re.IGNORECASE
    )
    if https_match:
        user_p, pass_p, owner, repo = https_match.groups()
        embedded_token = pass_p if pass_p else (
            user_p if user_p and (
                user_p.startswith("github_pat_") or
                user_p.startswith("ghp_") or
                user_p.startswith("gho_") or
                user_p.startswith("ghu_") or
                user_p.startswith("ghs_") or
                user_p.startswith("ghr_") or
                len(user_p) > 20
            ) else None
        )
        return owner, repo, embedded_token

    # SSH pattern
    ssh_match = re.match(r"^git@github\.com:([^/]+)/([^/.]+?)(?:\.git)?$", url, re.IGNORECASE)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2), None

    return None


def _check_via_smart_http(url: str, branch: str, start_time: float, provider: str = "github", repo_label: Optional[str] = None) -> Dict[str, Any]:
    """
    Fallback / rate-limit-immune Git Smart HTTP probe.
    Queries the /info/refs?service=git-upload-pack endpoint.
    """
    try:
        clean_url = url.rstrip("/")
        if not clean_url.endswith(".git"):
            probe_url = f"{clean_url}.git/info/refs?service=git-upload-pack"
        else:
            probe_url = f"{clean_url}/info/refs?service=git-upload-pack"

        resp = requests.get(probe_url, timeout=6.0, headers={"User-Agent": "git/2.40.0"})
        latency_ms = int((time.time() - start_time) * 1000)

        if resp.status_code == 200 and "git-upload-pack" in resp.headers.get("content-type", ""):
            refs_text = resp.text
            branch_ref = f"refs/heads/{branch}"
            has_branch = branch_ref in refs_text

            if has_branch or not branch:
                return {
                    "connected": True,
                    "status": "CONNECTED",
                    "provider": provider,
                    "repo": repo_label or url,
                    "branch": branch,
                    "message": f"Successfully connected to Git repository '{repo_label or url}' (Branch: '{branch}').",
                    "latency_ms": latency_ms
                }
            else:
                return {
                    "connected": False,
                    "status": "BRANCH_NOT_FOUND",
                    "provider": provider,
                    "repo": repo_label or url,
                    "branch": branch,
                    "message": f"Repository exists and is reachable, but branch '{branch}' was not found in remote references.",
                    "latency_ms": latency_ms
                }
        elif resp.status_code in (401, 403):
            return {
                "connected": False,
                "status": "AUTH_REQUIRED",
                "provider": provider,
                "repo": repo_label or url,
                "branch": branch,
                "message": "Access denied (HTTP 401/403). Repository is private or requires authentication credentials.",
                "latency_ms": latency_ms
            }
        elif resp.status_code == 404:
            return {
                "connected": False,
                "status": "NOT_FOUND",
                "provider": provider,
                "repo": repo_label or url,
                "branch": branch,
                "message": f"Git repository '{repo_label or url}' not found (HTTP 404). Verify the URL or check if the repository is private.",
                "latency_ms": latency_ms
            }
        else:
            return {
                "connected": False,
                "status": "HTTP_ERROR",
                "provider": provider,
                "repo": repo_label or url,
                "branch": branch,
                "message": f"Remote Git server returned HTTP {resp.status_code}.",
                "latency_ms": latency_ms
            }
    except requests.exceptions.Timeout:
        return {
            "connected": False,
            "status": "TIMEOUT",
            "provider": provider,
            "repo": repo_label or url,
            "branch": branch,
            "message": "Connection to remote Git server timed out after 6 seconds.",
            "latency_ms": int((time.time() - start_time) * 1000)
        }
    except Exception as e:
        return {
            "connected": False,
            "status": "NETWORK_ERROR",
            "provider": provider,
            "repo": repo_label or url,
            "branch": branch,
            "message": f"Network error connecting to Git server: {str(e)}",
            "latency_ms": int((time.time() - start_time) * 1000)
        }


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
        owner, repo, embedded_token = gh_parsed
        active_token = token or embedded_token
        repo_slug = f"{owner}/{repo}"

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "TDD-Intelligence-Platform/1.0"
        }
        if active_token:
            headers["Authorization"] = f"Bearer {active_token}"

        try:
            # Step A: Query GitHub REST API
            repo_api_url = f"https://api.github.com/repos/{owner}/{repo}"
            resp = requests.get(repo_api_url, headers=headers, timeout=6.0)

            # If rate limited and no active token provided, fallback gracefully to Git Smart HTTP probe
            if resp.status_code in (403, 429) and not active_token:
                clean_clone_url = f"https://github.com/{owner}/{repo}.git"
                return _check_via_smart_http(clean_clone_url, branch, start_time, provider="github", repo_label=repo_slug)

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
                        "repo": repo_slug,
                        "branch": branch,
                        "default_branch": default_branch,
                        "is_private": is_private,
                        "message": f"Successfully connected to GitHub repository '{repo_slug}' (Branch: '{branch}').",
                        "latency_ms": b_latency_ms
                    }
                elif b_resp.status_code == 404:
                    return {
                        "connected": False,
                        "status": "BRANCH_NOT_FOUND",
                        "provider": "github",
                        "repo": repo_slug,
                        "branch": branch,
                        "default_branch": default_branch,
                        "is_private": is_private,
                        "message": f"Repository '{repo_slug}' exists, but branch '{branch}' was not found. (Default branch is '{default_branch}').",
                        "latency_ms": b_latency_ms
                    }
                else:
                    return {
                        "connected": True,
                        "status": "CONNECTED_BRANCH_UNVERIFIED",
                        "provider": "github",
                        "repo": repo_slug,
                        "branch": branch,
                        "default_branch": default_branch,
                        "is_private": is_private,
                        "message": f"Connected to repository '{repo_slug}'. Branch verification returned status {b_resp.status_code}.",
                        "latency_ms": b_latency_ms
                    }

            elif resp.status_code == 404:
                return {
                    "connected": False,
                    "status": "NOT_FOUND",
                    "provider": "github",
                    "repo": repo_slug,
                    "branch": branch,
                    "message": f"GitHub repository '{repo_slug}' not found. Verify the URL or check if the repository is private.",
                    "latency_ms": int((time.time() - start_time) * 1000)
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
                    "repo": repo_slug,
                    "branch": branch,
                    "message": detail,
                    "latency_ms": int((time.time() - start_time) * 1000)
                }
            else:
                return {
                    "connected": False,
                    "status": "HTTP_ERROR",
                    "provider": "github",
                    "repo": repo_slug,
                    "branch": branch,
                    "message": f"GitHub returned HTTP {resp.status_code}: {resp.text[:120]}",
                    "latency_ms": int((time.time() - start_time) * 1000)
                }

        except (requests.exceptions.RequestException, Exception):
            # Fallback to Smart HTTP probe on network or transient error
            clean_clone_url = f"https://github.com/{owner}/{repo}.git"
            return _check_via_smart_http(clean_clone_url, branch, start_time, provider="github", repo_label=repo_slug)

    # 2. Generic HTTPS Git repository check
    if url.startswith("http://") or url.startswith("https://"):
        return _check_via_smart_http(url, branch, start_time, provider=git_provider or "git")

    return {
        "connected": False,
        "status": "INVALID_URL",
        "provider": git_provider or "git",
        "repo": url,
        "branch": branch,
        "message": "Invalid Git repository URL format. Please provide a valid HTTP/HTTPS GitHub or Git repository URL.",
        "latency_ms": 0
    }
