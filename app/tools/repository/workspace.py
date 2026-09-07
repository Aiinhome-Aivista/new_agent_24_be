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

    def find_root_package(self, lang: str = "java") -> str:
        """Detect the root package name from codebase (e.g. 'com.poc.crud' for Java)."""
        if not self.exists:
            return "com.app.tests" if lang in ("java", "kotlin") else ""

        ws = self.workspace_path
        if lang in ("java", "kotlin"):
            # 1. Search for *Application.java or files in src/main/java
            src_main_java = ws / "src" / "main" / "java"
            if src_main_java.exists():
                # Look for Spring Boot Application class first
                for p in src_main_java.rglob("*.java"):
                    if p.name.endswith("Application.java") or p.name.endswith("App.java"):
                        try:
                            content = p.read_text(encoding="utf-8", errors="replace")
                            for line in content.split("\n"):
                                line = line.strip()
                                if line.startswith("package ") and line.endswith(";"):
                                    return line.replace("package ", "").replace(";", "").strip()
                        except Exception:
                            pass
                # Any java file in src/main/java
                for p in src_main_java.rglob("*.java"):
                    try:
                        content = p.read_text(encoding="utf-8", errors="replace")
                        for line in content.split("\n"):
                            line = line.strip()
                            if line.startswith("package ") and line.endswith(";"):
                                full_pkg = line.replace("package ", "").replace(";", "").strip()
                                parts = full_pkg.split(".")
                                if len(parts) >= 2:
                                    return ".".join(parts[:3]) if len(parts) >= 3 else ".".join(parts[:2])
                    except Exception:
                        pass

            # 2. Fallback to pom.xml groupId
            pom_path = ws / "pom.xml"
            if pom_path.exists():
                try:
                    import xml.etree.ElementTree as ET
                    tree = ET.parse(pom_path)
                    root = tree.getroot()
                    # Remove namespace prefix if present
                    ns = {"mvn": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
                    gid_elem = root.find("mvn:groupId", ns) if ns else root.find("groupId")
                    if gid_elem is not None and gid_elem.text:
                        return gid_elem.text.strip()
                except Exception:
                    pass

            return "com.app.tests"

        elif lang == "python":
            for d in ["src", "app"]:
                if (ws / d).is_dir():
                    return d
            return "app"

        return ""

    def find_class_import(self, class_name: str, lang: str = "java") -> str:
        """Find the full import path for a given class name in the codebase."""
        if not self.exists or not class_name:
            return ""

        ws = self.workspace_path
        if lang in ("java", "kotlin"):
            src_main_java = ws / "src" / "main" / "java"
            if src_main_java.exists():
                for p in src_main_java.rglob(f"{class_name}.java"):
                    try:
                        content = p.read_text(encoding="utf-8", errors="replace")
                        for line in content.split("\n"):
                            line = line.strip()
                            if line.startswith("package ") and line.endswith(";"):
                                pkg = line.replace("package ", "").replace(";", "").strip()
                                return f"{pkg}.{class_name}"
                    except Exception:
                        pass
        elif lang == "python":
            for ext in [".py"]:
                for p in ws.rglob(f"*{ext}"):
                    if p.stem.lower() == class_name.lower():
                        try:
                            rel_path = p.relative_to(ws)
                            module_path = ".".join(rel_path.with_suffix("").parts)
                            return f"from {module_path} import {class_name}"
                        except Exception:
                            pass
        return ""

    def resolve_imports_for_functions(self, responsible_functions: list, lang: str = "java") -> list:
        """Resolves fully-qualified imports for all classes referenced in responsible_functions."""
        if not responsible_functions or not self.exists:
            return []

        imports = set()
        for fn in responsible_functions:
            # Extract class name (e.g. "AuthController.changePassword" -> "AuthController")
            cls_name = fn.split(".")[0].strip() if "." in fn else fn.strip()
            if not cls_name or cls_name in ("null", "UNKNOWN", "N/A"):
                continue

            resolved = self.find_class_import(cls_name, lang=lang)
            if resolved:
                if lang in ("java", "kotlin"):
                    imports.add(f"import {resolved};")
                elif lang == "python":
                    imports.add(resolved)
                else:
                    imports.add(f"import {{ {cls_name} }} from './{cls_name}';")

        return sorted(list(imports))

    def detect_base_url(self) -> str:
        """Detect the server base URL (e.g. http://localhost:8080 or http://localhost:5000) from project config."""
        if not self.exists:
            return "http://localhost:8080"

        ws = self.workspace_path
        port = None
        context_path = ""

        # 1. Check GitHub deployment workflows (e.g. .github/workflows/deploy.yml with PORT: 3035)
        for deploy_path in (ws / ".github" / "workflows").glob("*.yml") if (ws / ".github" / "workflows").exists() else []:
            try:
                content = deploy_path.read_text(encoding="utf-8", errors="replace")
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("PORT:") or line.startswith("PORT :") or line.startswith("SERVER_PORT:"):
                        val = line.split(":", 1)[1].strip().strip("'\"")
                        if val.isdigit():
                            port = val
                            break
            except Exception:
                pass

        # 2. Spring Boot application.properties or application.yml
        for prop_path in [
            ws / "src" / "main" / "resources" / "application.properties",
            ws / "src" / "main" / "resources" / "application.yml",
            ws / "src" / "main" / "resources" / "application.yaml",
            ws / "application.properties",
            ws / "application.yml",
        ]:
            if prop_path.exists():
                try:
                    content = prop_path.read_text(encoding="utf-8", errors="replace")
                    for line in content.split("\n"):
                        line = line.strip()
                        if line.startswith("server.port") and "=" in line:
                            val = line.split("=")[1].strip()
                            if val.isdigit():
                                port = val
                        elif line.startswith("server.servlet.context-path") and "=" in line:
                            context_path = line.split("=")[1].strip()
                        elif "port:" in line:
                            parts = line.split("port:")
                            val = parts[1].strip()
                            if val.isdigit():
                                port = val
                        elif "context-path:" in line:
                            context_path = line.split("context-path:")[1].strip()
                except Exception:
                    pass

        # 3. Check .env file or backend/config.py
        for env_path in [ws / ".env", ws / "backend" / ".env", ws / ".env.example"]:
            if not port and env_path.exists():
                try:
                    content = env_path.read_text(encoding="utf-8", errors="replace")
                    for line in content.split("\n"):
                        line = line.strip()
                        if line.startswith("PORT=") or line.startswith("SERVER_PORT="):
                            val = line.split("=")[1].strip()
                            if val.isdigit():
                                port = val
                except Exception:
                    pass

        structure = self.find_project_structure()
        lang = structure.get("language")
        if not port:
            if lang in ("java", "kotlin"):
                port = "8080"
            elif lang == "python":
                port = "8000"
            elif lang in ("typescript", "javascript"):
                port = "3000"
            else:
                port = "8080"

        context_path = context_path.strip().rstrip("/")
        if context_path and not context_path.startswith("/"):
            context_path = f"/{context_path}"

        return f"http://localhost:{port}{context_path}"

    def extract_api_route_context(self, max_files: int = 25, max_bytes_per_file: int = 6000) -> str:
        """Extract source code snippets focusing specifically on API Controllers, Routes, Handlers, DTOs, and Models."""
        if not self.exists:
            return ""

        structure = self.find_project_structure()
        lang = structure.get("language", "")
        ext_map = {
            "java": [".java"],
            "kotlin": [".kt"],
            "python": [".py"],
            "typescript": [".ts", ".tsx"],
            "javascript": [".js", ".jsx"],
        }
        extensions = ext_map.get(lang, [".java", ".py", ".ts", ".js"])
        all_files = self.list_files(extensions=extensions)

        skip_patterns = ["test/", "tests/", "__test__", "node_modules/", "build/", "target/",
                         ".gradle/", "dist/", ".git/", "vendor/"]
        valid_files = [f for f in all_files if not any(p in f.lower() for p in skip_patterns)]

        # Priority keywords for API route definitions & models
        api_keywords = [
            "controller", "resource", "router", "route", "handler", "endpoint",
            "dto", "request", "response", "schema", "model", "entity", "service"
        ]

        def api_file_priority(path: str):
            lower = path.lower()
            for i, kw in enumerate(api_keywords):
                if kw in lower:
                    return i
            return len(api_keywords)

        # Sort so controllers and DTOs come first
        api_files = [f for f in valid_files if any(kw in f.lower() for kw in api_keywords)]
        if not api_files:
            api_files = valid_files

        api_files.sort(key=api_file_priority)
        api_files = api_files[:max_files]

        parts = []
        for f in api_files:
            try:
                content = self.read_file(f, max_size=max_bytes_per_file)
                parts.append(f"=== File: {f} ===\n{content}")
            except Exception:
                continue

        return "\n\n".join(parts)

    def parse_codebase_routes(self) -> list:
        """Statically scans codebase files to extract EXACT implemented REST API endpoints."""
        if not self.exists:
            return []
        
        all_files = self.list_files()
        routes = []
        import re

        for f in all_files:
            lower = f.lower()
            if any(skip in lower for skip in ("test", "node_modules", "target", "build", ".git", "dist")):
                continue
            if not any(f.endswith(ext) for ext in (".py", ".java", ".ts", ".js", ".kt", ".cs", ".go")):
                continue
            
            try:
                content = self.read_file(f, max_size=50000)
            except Exception:
                continue

            # 1. FastAPI / Flask / Python
            py_prefix = ""
            py_prefix_match = re.search(r'(?:APIRouter|Blueprint)\s*\([^)]*?(?:prefix|url_prefix)\s*=\s*["\']([^"\']+)["\']', content)
            if py_prefix_match:
                py_prefix = py_prefix_match.group(1).rstrip("/")

            py_matches = re.findall(r'@(?:router|app)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', content, re.IGNORECASE)
            for m, p in py_matches:
                clean_p = p.strip()
                full_p = f"{py_prefix}/{clean_p.lstrip('/')}" if py_prefix else clean_p
                if not full_p.startswith("/"):
                    full_p = f"/{full_p}"
                routes.append({"method": m.upper(), "path": full_p, "source_file": f})

            flask_route_matches = re.findall(r'@(?:app|blueprint|bp|[a-zA-Z0-9_]+_bp)\.route\s*\(\s*["\']([^"\']+)["\'](?:.*?methods\s*=\s*\[(.*?)\])?', content, re.IGNORECASE)
            for p, methods_str in flask_route_matches:
                m_list = re.findall(r'["\'](GET|POST|PUT|DELETE|PATCH)["\']', methods_str, re.IGNORECASE) if methods_str else ["GET"]
                clean_p = p.strip()
                full_p = f"{py_prefix}/{clean_p.lstrip('/')}" if py_prefix else clean_p
                if not full_p.startswith("/"):
                    full_p = f"/{full_p}"
                for m in m_list:
                    routes.append({"method": m.upper(), "path": full_p, "source_file": f})

            # 2. Spring Boot / Java / Kotlin
            class_prefix = ""
            class_req = re.search(r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']', content)
            if class_req:
                class_prefix = class_req.group(1).rstrip("/")

            spring_matches = re.findall(r'@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\s*(?:\(\s*(?:value\s*=\s*)?["\']?([^"\'\)]*)["\']?\s*\))?', content)
            for annot, p in spring_matches:
                verb = annot.replace("Mapping", "").upper()
                clean_p = p.strip() if p else ""
                full_p = f"{class_prefix}/{clean_p.lstrip('/')}" if class_prefix or clean_p else (clean_p or "/")
                if not full_p.startswith("/"):
                    full_p = f"/{full_p}"
                routes.append({"method": verb, "path": full_p, "source_file": f})

            # 3. Express / Node / NestJS
            nest_prefix = ""
            nest_ctrl = re.search(r'@Controller\s*\(\s*["\']?([^"\'\)]*)["\']?\s*\)', content)
            if nest_ctrl:
                nest_prefix = nest_ctrl.group(1).strip().rstrip("/")

            js_matches = re.findall(r'(?:router|app)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', content, re.IGNORECASE)
            for m, p in js_matches:
                clean_p = p.strip()
                if not clean_p.startswith("/"):
                    clean_p = f"/{clean_p}"
                routes.append({"method": m.upper(), "path": clean_p, "source_file": f})

            nest_matches = re.findall(r'@(Get|Post|Put|Delete|Patch)\s*\(\s*["\']?([^"\'\)]*)["\']?\s*\)', content)
            for annot, p in nest_matches:
                verb = annot.upper()
                clean_p = p.strip() if p else ""
                full_p = f"{nest_prefix}/{clean_p.lstrip('/')}" if nest_prefix or clean_p else (clean_p or "/")
                if not full_p.startswith("/"):
                    full_p = f"/{full_p}"
                routes.append({"method": verb, "path": full_p, "source_file": f})

        # Deduplicate routes
        seen = set()
        deduped_routes = []
        for r in routes:
            k = (r["method"], r["path"])
            if k not in seen:
                seen.add(k)
                deduped_routes.append(r)

        return deduped_routes

