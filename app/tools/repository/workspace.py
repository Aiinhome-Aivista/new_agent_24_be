"""
Git workspace manager. Clones repos into a project-scoped workspace directory,
pulls latest changes, and provides file-reading utilities for agents.

Security:
  - Shallow clone (--depth 50) to limit disk usage.
  - Single-branch checkout to reduce attack surface.
  - File reads are restricted to the workspace directory.
"""
import subprocess
import os
import json
from pathlib import Path
from app.config import Config

WORKSPACE_ROOT = getattr(Config, 'GIT_WORKSPACE_ROOT', './workspaces')


class GitWorkspace:
    """Project-scoped git workspace for code analysis."""

    def __init__(self, project_uuid: str, repo_url: str, branch: str = "main"):
        self.project_uuid = project_uuid
        self.repo_url = repo_url
        self.branch = branch
        self.workspace_path = Path(WORKSPACE_ROOT) / project_uuid

    @property
    def exists(self) -> bool:
        return (self.workspace_path / ".git").exists()

    def clone_or_pull(self) -> dict:
        """Clone the repo if not exists, otherwise pull latest. Returns status dict."""
        try:
            if self.exists:
                result = subprocess.run(
                    ["git", "pull", "origin", self.branch],
                    cwd=str(self.workspace_path),
                    capture_output=True, text=True, timeout=120
                )
                return {
                    "action": "pulled",
                    "success": result.returncode == 0,
                    "output": result.stdout.strip(),
                    "error": result.stderr.strip() if result.returncode != 0 else None,
                }
            else:
                self.workspace_path.mkdir(parents=True, exist_ok=True)
                result = subprocess.run(
                    ["git", "clone", "--branch", self.branch,
                     "--single-branch", "--depth", "50",
                     self.repo_url, str(self.workspace_path)],
                    capture_output=True, text=True, timeout=300
                )
                return {
                    "action": "cloned",
                    "success": result.returncode == 0,
                    "output": result.stdout.strip(),
                    "error": result.stderr.strip() if result.returncode != 0 else None,
                }
        except subprocess.TimeoutExpired:
            return {"action": "timeout", "success": False, "error": "Git operation timed out"}
        except FileNotFoundError:
            return {"action": "error", "success": False, "error": "git is not installed or not on PATH"}
        except Exception as e:
            return {"action": "error", "success": False, "error": str(e)}

    def list_files(self, extensions=None) -> list:
        """List all tracked files, optionally filtered by extension."""
        if not self.exists:
            return []
        try:
            result = subprocess.run(
                ["git", "ls-files"],
                cwd=str(self.workspace_path),
                capture_output=True, text=True, timeout=30
            )
            files = [f for f in result.stdout.strip().split("\n") if f]
            if extensions:
                files = [f for f in files if any(f.endswith(ext) for ext in extensions)]
            return files
        except Exception:
            return []

    def read_file(self, relative_path: str, max_size: int = 50000) -> str:
        """Read a file from the workspace. Path traversal is prevented."""
        full_path = (self.workspace_path / relative_path).resolve()
        # Security: prevent path traversal
        if not str(full_path).startswith(str(self.workspace_path.resolve())):
            raise ValueError(f"Path traversal attempt: {relative_path}")
        if not full_path.is_file():
            raise FileNotFoundError(f"File not found: {relative_path}")
        content = full_path.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_size:
            content = content[:max_size] + f"\n\n... [truncated at {max_size} bytes] ..."
        return content

    def find_project_structure(self) -> dict:
        """Detect build tool, framework, entry points, and test directories."""
        structure = {
            "build_tool": None,
            "framework": None,
            "language": None,
            "source_dirs": [],
            "test_dirs": [],
            "config_files": [],
        }

        if not self.exists:
            return structure

        ws = self.workspace_path

        # Java / Spring Boot
        if (ws / "pom.xml").exists():
            structure["build_tool"] = "maven"
            structure["language"] = "java"
            structure["source_dirs"] = ["src/main/java"]
            structure["test_dirs"] = ["src/test/java"]
            structure["config_files"].append("pom.xml")
            try:
                pom_content = (ws / "pom.xml").read_text(errors="replace")
                if "spring-boot" in pom_content:
                    structure["framework"] = "spring-boot"
            except Exception:
                pass

        elif (ws / "build.gradle").exists() or (ws / "build.gradle.kts").exists():
            structure["build_tool"] = "gradle"
            structure["language"] = "java"
            structure["source_dirs"] = ["src/main/java"]
            structure["test_dirs"] = ["src/test/java"]
            config_file = "build.gradle.kts" if (ws / "build.gradle.kts").exists() else "build.gradle"
            structure["config_files"].append(config_file)
            try:
                gradle_content = (ws / config_file).read_text(errors="replace")
                if "spring-boot" in gradle_content or "org.springframework.boot" in gradle_content:
                    structure["framework"] = "spring-boot"
            except Exception:
                pass

        # Node.js / TypeScript
        elif (ws / "package.json").exists():
            structure["build_tool"] = "npm"
            structure["config_files"].append("package.json")
            try:
                pkg = json.loads((ws / "package.json").read_text())
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if "typescript" in deps:
                    structure["language"] = "typescript"
                else:
                    structure["language"] = "javascript"
                if "express" in deps:
                    structure["framework"] = "express"
                elif "next" in deps:
                    structure["framework"] = "next"
                elif "nestjs" in deps or "@nestjs/core" in deps:
                    structure["framework"] = "nestjs"
            except Exception:
                structure["language"] = "javascript"
            structure["source_dirs"] = ["src"]
            structure["test_dirs"] = ["test", "tests", "__tests__", "src/__tests__"]

        # Python
        elif (ws / "requirements.txt").exists() or (ws / "pyproject.toml").exists() or (ws / "setup.py").exists():
            structure["language"] = "python"
            if (ws / "pyproject.toml").exists():
                structure["build_tool"] = "poetry/pip"
                structure["config_files"].append("pyproject.toml")
            elif (ws / "requirements.txt").exists():
                structure["build_tool"] = "pip"
                structure["config_files"].append("requirements.txt")
            structure["source_dirs"] = ["src", "app"]
            structure["test_dirs"] = ["tests", "test"]

        # Filter to dirs that actually exist
        structure["source_dirs"] = [d for d in structure["source_dirs"] if (ws / d).is_dir()]
        structure["test_dirs"] = [d for d in structure["test_dirs"] if (ws / d).is_dir()]

        return structure

    def get_source_summary(self, max_files: int = 30, max_bytes_per_file: int = 8000) -> str:
        """Build a summary of key source files for LLM context."""
        if not self.exists:
            return ""

        structure = self.find_project_structure()
        lang = structure.get("language", "")

        # Extension map by language
        ext_map = {
            "java": [".java"],
            "kotlin": [".kt"],
            "python": [".py"],
            "typescript": [".ts", ".tsx"],
            "javascript": [".js", ".jsx"],
        }
        extensions = ext_map.get(lang, [".java", ".py", ".ts", ".js"])

        # Get relevant source files (prioritize source dirs, skip tests/configs)
        all_files = self.list_files(extensions=extensions)

        # Exclude test files, build outputs, generated code
        skip_patterns = ["test/", "tests/", "__test__", "node_modules/", "build/", "target/",
                         ".gradle/", "dist/", ".git/", "vendor/"]
        source_files = [f for f in all_files if not any(p in f.lower() for p in skip_patterns)]

        # Prioritize: controllers > services > models > repositories > config
        priority_keywords = ["controller", "service", "model", "entity", "repository", "config",
                             "handler", "route", "middleware", "dto", "schema"]

        def file_priority(path):
            lower = path.lower()
            for i, kw in enumerate(priority_keywords):
                if kw in lower:
                    return i
            return len(priority_keywords)

        source_files.sort(key=file_priority)
        source_files = source_files[:max_files]

        # Build summary
        parts = []
        for f in source_files:
            try:
                content = self.read_file(f, max_size=max_bytes_per_file)
                parts.append(f"--- {f} ---\n{content}")
            except Exception:
                continue

        return "\n\n".join(parts)
