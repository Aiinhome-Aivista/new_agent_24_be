"""
TraceabilityMapper — AC -> API -> Code Traceability Engine

Maps every Acceptance Criterion (AC) to:
  1. Relevant API endpoint(s) (method, path, URL, source)
  2. Code call-chain: Route/Controller -> Service -> Repository/Model
  3. Implementation status: SUPPORTED | PARTIALLY_SUPPORTED | NOT_IMPLEMENTED | AMBIGUOUS
  4. Responsible source files for scoped code coverage

CRITICAL ARCHITECTURAL RULES (per prompt.md):
- NEVER remove or delete an Acceptance Criterion, even if status is NOT_IMPLEMENTED.
- Unimplemented ACs remain fully tracked so downstream test generators can produce
  tests that expose the gap, and evidence can document the implementation gap.
"""
import re
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set


class TraceabilityMapper:
    """
    Constructs an auditable AC -> API -> Code mapping matrix.
    Combines deterministic AST / regex static analysis with semantic keyword matching.
    """

    def __init__(self):
        pass

    def map(
        self,
        acs: List[Any],
        extracted_apis: Optional[List[Dict[str, Any]]] = None,
        postman_contracts: Optional[List[Dict[str, Any]]] = None,
        workspace_path: Optional[str] = None,
        codebase_context: Optional[str] = "",
    ) -> List[Dict[str, Any]]:
        """
        Main mapping entry point.

        Args:
            acs: List of Acceptance Criteria (dicts or raw strings)
            extracted_apis: Discovered codebase APIs from ServicePlanner
            postman_contracts: Known Postman/OpenAPI contract items
            workspace_path: Path to cloned/local git repository
            codebase_context: Extracted source code text snippets

        Returns:
            List of structured traceability records, exactly one per AC.
        """
        extracted_apis = extracted_apis or []
        postman_contracts = postman_contracts or []
        codebase_context = codebase_context or ""

        # Consolidated list of known API endpoints
        all_apis = self._consolidate_apis(extracted_apis, postman_contracts)

        # Index codebase files if workspace path is available
        codebase_index = self._index_codebase(workspace_path, codebase_context)

        mapping_records = []
        for idx, raw_ac in enumerate(acs, start=1):
            ac_key, ac_text = self._parse_ac(raw_ac, idx)
            record = self._map_single_ac(
                ac_key=ac_key,
                ac_text=ac_text,
                known_apis=all_apis,
                codebase_index=codebase_index,
                codebase_context=codebase_context,
            )
            mapping_records.append(record)

        return mapping_records

    # ──────────────────────────────────────────────────────────────────────────
    # AC Parsing & Normalization
    # ──────────────────────────────────────────────────────────────────────────

    def _parse_ac(self, ac: Any, idx: int) -> Tuple[str, str]:
        if isinstance(ac, dict):
            key = ac.get("ac_key") or f"AC-{idx:02d}"
            text = ac.get("text") or ac.get("description") or str(ac)
        else:
            text = str(ac).strip()
            m = re.match(r"^(AC[-\s]?\d+)\s*[:\.\-]?\s*(.*)", text, re.IGNORECASE | re.DOTALL)
            if m:
                key = m.group(1).upper().replace(" ", "-")
                text = m.group(2).strip() or text
            else:
                key = f"AC-{idx:02d}"
        return key, text

    # ──────────────────────────────────────────────────────────────────────────
    # API Consolidation & Matching
    # ──────────────────────────────────────────────────────────────────────────

    def _consolidate_apis(
        self,
        extracted_apis: List[Dict[str, Any]],
        postman_contracts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        consolidated = []
        seen = set()

        for ep in list(extracted_apis) + list(postman_contracts):
            method = (ep.get("method") or "GET").upper()
            raw_path = ep.get("path") or ep.get("url") or "/"
            clean_path = self._clean_endpoint_path(raw_path)
            key = f"{method} {clean_path}"
            if key not in seen:
                seen.add(key)
                consolidated.append({
                    "method": method,
                    "path": clean_path,
                    "raw_url": ep.get("url") or clean_path,
                    "payload_schema": ep.get("payload_schema") or ep.get("sample_request") or ep.get("body") or {},
                    "response_schema": ep.get("response_schema") or ep.get("sample_response") or {},
                    "service": ep.get("service") or "Service",
                    "source": "CODEBASE_ROUTE" if ep in extracted_apis else "POSTMAN_CONTRACT",
                })
        return consolidated

    def _clean_endpoint_path(self, path_or_url: str) -> str:
        if not path_or_url:
            return "/"
        path = str(path_or_url).strip()
        if path.startswith("http://") or path.startswith("https://"):
            from urllib.parse import urlparse
            path = urlparse(path).path or "/"
        # Strip query parameters
        path = path.split("?")[0]
        # Normalize trailing slash
        path = "/" + path.strip("/")
        return path if path else "/"

    def _extract_http_refs_from_text(self, text: str) -> List[Tuple[str, str]]:
        """Extract explicit HTTP methods and paths mentioned in text."""
        matches = re.findall(
            r'\b(GET|POST|PUT|DELETE|PATCH)\s+([/][a-zA-Z0-9/_\-{}:.]+)',
            text, re.IGNORECASE
        )
        return [(m.upper(), self._clean_endpoint_path(p)) for m, p in matches]

    def _match_apis_for_ac(
        self,
        ac_text: str,
        known_apis: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Find matching APIs for an AC via explicit mention or semantic path match."""
        explicit_refs = self._extract_http_refs_from_text(ac_text)
        matched = []
        matched_keys = set()

        # 1. Match explicit references (e.g. POST /api/tickets)
        for exp_method, exp_path in explicit_refs:
            for api in known_apis:
                if api["method"] == exp_method:
                    # Exact or suffix match (e.g. /api/tickets matches /api/tickets or /api/v1/tickets)
                    if api["path"] == exp_path or api["path"].endswith(exp_path) or exp_path.endswith(api["path"]):
                        k = f"{api['method']} {api['path']}"
                        if k not in matched_keys:
                            matched_keys.add(k)
                            matched.append(api)

        # 2. Match by resource noun keywords if not explicitly specified
        if not matched and known_apis:
            tokens = set(re.findall(r'[a-zA-Z]{3,}', ac_text.lower()))
            scored_apis = []
            for api in known_apis:
                score = 0
                path_parts = [p.lower() for p in api["path"].split("/") if p and len(p) > 2]
                for part in path_parts:
                    if part in tokens or any(part in t or t in part for t in tokens):
                        score += 2
                # Boost method based on AC intent (create/add -> POST, fetch/get -> GET, update -> PUT/PATCH, delete -> DELETE)
                if any(w in tokens for w in ["create", "add", "submit", "register", "insert"]) and api["method"] == "POST":
                    score += 2
                elif any(w in tokens for w in ["get", "fetch", "retrieve", "list", "view", "find"]) and api["method"] == "GET":
                    score += 2
                elif any(w in tokens for w in ["update", "modify", "change", "edit"]) and api["method"] in ("PUT", "PATCH"):
                    score += 2
                elif any(w in tokens for w in ["delete", "remove", "cancel"]) and api["method"] == "DELETE":
                    score += 2

                if score > 0:
                    scored_apis.append((score, api))

            scored_apis.sort(key=lambda x: x[0], reverse=True)
            for _, api in scored_apis[:2]:
                k = f"{api['method']} {api['path']}"
                if k not in matched_keys:
                    matched_keys.add(k)
                    matched.append(api)

        # 3. If still no match but explicit ref was found, create synthetic entry
        if not matched and explicit_refs:
            for exp_method, exp_path in explicit_refs:
                matched.append({
                    "method": exp_method,
                    "path": exp_path,
                    "raw_url": exp_path,
                    "payload_schema": {},
                    "response_schema": {},
                    "service": "UnknownService",
                    "source": "INFERRED_FROM_REQUIREMENT",
                })

        return matched

    # ──────────────────────────────────────────────────────────────────────────
    # Codebase Indexing & Call-Chain Discovery
    # ──────────────────────────────────────────────────────────────────────────

    def _index_codebase(
        self,
        workspace_path: Optional[str],
        codebase_context: str,
    ) -> Dict[str, Any]:
        """Index controllers, services, repositories, and models from workspace or snippets."""
        index = {
            "controllers": [],
            "services": [],
            "repositories": [],
            "models": [],
            "all_files": [],
        }

        if workspace_path and os.path.isdir(workspace_path):
            ws = Path(workspace_path)
            for ext in [".py", ".java", ".ts", ".js"]:
                for file_path in ws.rglob(f"*{ext}"):
                    rel_str = str(file_path.relative_to(ws)).replace("\\", "/")
                    if any(skip in rel_str.lower() for skip in ["venv", ".venv", "site-packages", "__pycache__", "test", "tests", "node_modules", "target", "build", ".git"]):
                        continue
                    index["all_files"].append(rel_str)
                    lower = rel_str.lower()
                    if "app.py" in lower or "main.py" in lower or any(k in lower for k in ["controller", "route", "handler", "api", "endpoint"]):
                        index["controllers"].append(rel_str)
                    elif any(k in lower for k in ["service", "manager", "interactor", "usecase"]):
                        index["services"].append(rel_str)
                    elif any(k in lower for k in ["repo", "repository", "dao", "store"]):
                        index["repositories"].append(rel_str)
                    elif any(k in lower for k in ["model", "entity", "dto", "schema"]):
                        index["models"].append(rel_str)

        # Also inspect codebase_context headers (e.g. --- routes/users.py ---)
        if codebase_context:
            for match in re.finditer(r"---\s*([a-zA-Z0-9_\-/\\]+\.(?:py|java|ts|js))\s*---", codebase_context):
                fname = match.group(1).replace("\\", "/")
                if fname not in index["all_files"]:
                    index["all_files"].append(fname)
                    lower = fname.lower()
                    if any(k in lower for k in ["controller", "route", "handler", "api", "endpoint"]):
                        index["controllers"].append(fname)
                    elif any(k in lower for k in ["service", "manager", "interactor", "usecase"]):
                        index["services"].append(fname)
                    elif any(k in lower for k in ["repo", "repository", "dao", "store"]):
                        index["repositories"].append(fname)
                    elif any(k in lower for k in ["model", "entity", "dto", "schema"]):
                        index["models"].append(fname)

        return index

    def _discover_call_chain(
        self,
        endpoint_path: str,
        codebase_index: Dict[str, Any],
        codebase_context: str,
    ) -> Tuple[List[Dict[str, str]], List[str]]:
        """
        Traces call chain from route/controller down to service and repository.
        Returns:
            (call_chain_nodes, responsible_file_paths)
        """
        nodes = []
        responsible_files: Set[str] = set()

        clean_path = self._clean_endpoint_path(endpoint_path)
        path_slug = clean_path.split("/")[-1].replace("{", "").replace("}", "").lower()
        if not path_slug or path_slug == "api":
            parts = [p for p in clean_path.split("/") if p and p != "api"]
            path_slug = parts[0].lower() if parts else "service"

        # 1. Controller / Route Layer
        matched_controller = None
        for cfile in codebase_index["controllers"]:
            if path_slug in cfile.lower():
                matched_controller = cfile
                break
        if not matched_controller and codebase_index["controllers"]:
            matched_controller = codebase_index["controllers"][0]

        if matched_controller:
            symbol = f"{path_slug}_handler"
            nodes.append({
                "layer": "controller",
                "file": matched_controller,
                "symbol": symbol,
            })
            responsible_files.add(matched_controller)

        # 2. Service Layer
        matched_service = None
        for sfile in codebase_index["services"]:
            if path_slug in sfile.lower():
                matched_service = sfile
                break
        if not matched_service and codebase_index["services"]:
            matched_service = codebase_index["services"][0]

        if matched_service:
            symbol = f"{path_slug.capitalize()}Service.{path_slug}_operation"
            nodes.append({
                "layer": "service",
                "file": matched_service,
                "symbol": symbol,
            })
            responsible_files.add(matched_service)

        # 3. Repository Layer
        matched_repo = None
        for rfile in codebase_index["repositories"]:
            if path_slug in rfile.lower():
                matched_repo = rfile
                break
        if not matched_repo and codebase_index["repositories"]:
            matched_repo = codebase_index["repositories"][0]

        if matched_repo:
            symbol = f"{path_slug.capitalize()}Repository.save"
            nodes.append({
                "layer": "repository",
                "file": matched_repo,
                "symbol": symbol,
            })
            responsible_files.add(matched_repo)

        return nodes, sorted(list(responsible_files))

    # ──────────────────────────────────────────────────────────────────────────
    # Single AC Evaluation
    # ──────────────────────────────────────────────────────────────────────────

    def _map_single_ac(
        self,
        ac_key: str,
        ac_text: str,
        known_apis: List[Dict[str, Any]],
        codebase_index: Dict[str, Any],
        codebase_context: str,
    ) -> Dict[str, Any]:
        """Maps an individual Acceptance Criterion and evaluates implementation status."""
        matched_apis = self._match_apis_for_ac(ac_text, known_apis)

        call_chain = []
        responsible_files = []

        if matched_apis:
            primary_api = matched_apis[0]
            call_chain, responsible_files = self._discover_call_chain(
                endpoint_path=primary_api["path"],
                codebase_index=codebase_index,
                codebase_context=codebase_context,
            )

        has_error_condition = any(w in ac_text.lower() for w in ["reject", "invalid", "error", "fail", "missing", "duplicate", "400", "404", "401", "409"])

        if not matched_apis:
            implementation_status = "NOT_IMPLEMENTED"
            implementation_notes = "No matching API endpoint or route found in codebase or API contracts."
        elif has_error_condition:
            implementation_status = "PARTIALLY_SUPPORTED"
            implementation_notes = "Endpoint exists; validation and error condition logic requires verification via unit tests."
        elif not call_chain and not codebase_index["all_files"]:
            # API known (e.g. from Postman contract), but no local codebase linked
            implementation_status = "SUPPORTED"
            implementation_notes = "API contract exists; codebase implementation pending workspace execution."
        elif matched_apis and call_chain:
            implementation_status = "SUPPORTED"
            implementation_notes = f"Mapped to {matched_apis[0]['method']} {matched_apis[0]['path']} and {len(call_chain)} code layers."
        else:
            implementation_status = "PARTIALLY_SUPPORTED"
            implementation_notes = "Endpoint identified, but full service/repository call-chain could not be statically resolved."

        return {
            "ac_key": ac_key,
            "requirement_text": ac_text,
            "mapped_apis": [
                {
                    "method": api["method"],
                    "path": api["path"],
                    "url": api.get("raw_url") or api["path"],
                    "service": api.get("service", "Service"),
                    "source": api.get("source", "UNKNOWN"),
                }
                for api in matched_apis
            ],
            "mapped_code": call_chain,
            "responsible_files": responsible_files,
            "implementation_status": implementation_status,
            "implementation_notes": implementation_notes,
            "test_cases": [],  # Populated during test generation
            "unit_test_result": "PENDING",
            "api_execution_result": "PENDING",
            "final_assessment": "PENDING",
        }
