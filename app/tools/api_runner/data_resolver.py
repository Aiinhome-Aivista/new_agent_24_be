import re
import json
import requests
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple


class DynamicDataResolver:
    """
    Intelligently discovers and hydrates authentic, live database data into test payloads and URL params.
    Uses:
    1. Pre-flight Live API Queries (e.g., calling GET /api/prospects to grab real IDs for POST /api/prospects/analyze)
    2. Git Codebase Seed & Fixture Scans (extracting IDs and Enums from seeds.sql, fixtures.json, test data)
    """

    _cache: Dict[str, Any] = {}

    @classmethod
    def resolve_test_case_data(
        cls,
        tc: Dict[str, Any],
        environment: str = "http://localhost:8080",
        workspace_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """Hydrates real live data into the test case's request_spec, endpoint URL, and payload."""
        if not isinstance(tc, dict):
            return tc

        req_spec = tc.get("request_spec") or {}
        method = (req_spec.get("method") or tc.get("method") or "POST").upper()
        raw_endpoint = str(req_spec.get("endpoint") or tc.get("url") or tc.get("path") or "/api").strip()
        scenario_type = str(tc.get("scenario_type") or "positive").upper()

        payload = tc.get("actual_payload") or tc.get("payload") or req_spec.get("body") or tc.get("test_data")
        if isinstance(payload, str) and payload.strip().startswith("{"):
            try:
                payload = json.loads(payload)
            except Exception:
                pass

        # If it's a negative scenario explicitly testing non-existent data, keep non-existent value
        if "NEGATIVE" in scenario_type and ("404" in str(tc.get("title", "")) or "not found" in str(tc.get("description", "")).lower()):
            return tc

        # 1. Check if URL or payload contains ID placeholders
        has_url_param = "{" in raw_endpoint and "}" in raw_endpoint
        has_id_in_payload = isinstance(payload, dict) and any("id" in k.lower() or "prospect" in k.lower() for k in payload.keys())

        if not has_url_param and not has_id_in_payload and method in ("GET", "DELETE"):
            return tc

        # 2. Derive entity listing endpoint (e.g. /api/prospects from /api/prospects/analyze or /api/prospects/{id})
        entity_endpoint = cls._derive_entity_listing_endpoint(raw_endpoint)

        # 3. Pre-flight Live Fetch
        live_item = None
        if entity_endpoint and environment and (environment.startswith("http://") or environment.startswith("https://")):
            live_item = cls._fetch_live_sample(environment, entity_endpoint)

        # 4. Fallback: Workspace Seed / Fixture scan
        if not live_item and workspace_path:
            live_item = cls._scan_workspace_seeds(workspace_path, raw_endpoint)

        if not live_item:
            return tc

        # 5. Hydrate URL path parameters (e.g. /api/prospects/{id} -> /api/prospects/PR-88219)
        hydrated_endpoint = raw_endpoint
        if has_url_param:
            for param_match in re.findall(r"\{([a-zA-Z0-9_-]+)\}", raw_endpoint):
                val = cls._find_value_for_key(live_item, param_match)
                if val is not None:
                    hydrated_endpoint = hydrated_endpoint.replace(f"{{{param_match}}}", str(val))

            req_spec["endpoint"] = hydrated_endpoint
            tc["endpoint"] = hydrated_endpoint
            tc["url"] = hydrated_endpoint

        # 6. Hydrate Request Payload fields with live data
        if isinstance(payload, dict) and len(payload) > 0:
            hydrated_payload = dict(payload)
            for k, v in payload.items():
                k_low = k.lower()
                # If value is placeholder or template, inject real live value
                if isinstance(v, str) and (v.startswith("<") or v.startswith("PR-") or v.startswith("POL-") or "sample" in v or "100" in v or "valid_" in v):
                    live_val = cls._find_value_for_key(live_item, k)
                    if live_val is not None:
                        hydrated_payload[k] = live_val
                elif "id" in k_low and (v in (1001, "1001", "PR-10029", "USR-9901", "POL-8821")):
                    live_val = cls._find_value_for_key(live_item, k)
                    if live_val is not None:
                        hydrated_payload[k] = live_val

            req_spec["body"] = hydrated_payload
            tc["actual_payload"] = hydrated_payload
            tc["payload"] = hydrated_payload
            tc["test_data"] = hydrated_payload

        return tc

    @classmethod
    def _derive_entity_listing_endpoint(cls, endpoint: str) -> Optional[str]:
        """Extracts the base collection endpoint (e.g., '/api/prospects' from '/api/prospects/analyze' or '/api/prospects/{id}')."""
        clean = endpoint.split("?")[0].rstrip("/")
        parts = [p for p in clean.split("/") if p]
        if not parts:
            return None

        # Filter out action verbs or param placeholders
        action_verbs = {"analyze", "details", "detail", "search", "filter", "create", "update", "delete", "export", "import"}
        filtered_parts = []
        for p in parts:
            if p.startswith("{") and p.endswith("}"):
                continue
            if p.lower() in action_verbs:
                continue
            filtered_parts.append(p)

        if filtered_parts:
            return "/" + "/".join(filtered_parts)
        return "/" + "/".join(parts[:2]) if len(parts) >= 2 else None

    @classmethod
    def _fetch_live_sample(cls, base_url: str, entity_endpoint: str) -> Optional[Dict[str, Any]]:
        """Hits the live GET endpoint with 5s timeout to retrieve authentic database records."""
        full_url = f"{base_url.rstrip('/')}{entity_endpoint}"
        if full_url in cls._cache:
            return cls._cache[full_url]

        try:
            resp = requests.get(full_url, timeout=5.0, headers={"Accept": "application/json"})
            if resp.status_code == 200:
                data = resp.json()
                item = cls._extract_first_item(data)
                if item and isinstance(item, dict):
                    cls._cache[full_url] = item
                    print(f"[DynamicDataResolver] Successfully fetched live record from {full_url}: ID={item.get('id') or item.get('prospect_id')}")
                    return item
        except Exception as e:
            # Silent fallback if target live server endpoint isn't up yet
            pass
        return None

    @classmethod
    def _extract_first_item(cls, data: Any) -> Optional[Dict[str, Any]]:
        """Extracts the first dictionary item from various API response shapes."""
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            return data[0]
        if isinstance(data, dict):
            for k in ("items", "data", "results", "prospects", "users", "records"):
                sub = data.get(k)
                if isinstance(sub, list) and len(sub) > 0 and isinstance(sub[0], dict):
                    return sub[0]
            # Dict itself might be an object
            if "id" in data or "prospect_id" in data or "uuid" in data:
                return data
        return None

    @classmethod
    def _find_value_for_key(cls, live_item: Dict[str, Any], target_key: str) -> Any:
        """Fuzzy matches a key inside the live item dictionary."""
        target_norm = target_key.lower().replace("_", "").replace("-", "")
        for k, v in live_item.items():
            k_norm = k.lower().replace("_", "").replace("-", "")
            if k_norm == target_norm:
                return v

        # Common ID fallbacks
        if "id" in target_key.lower():
            for fallback in ("id", "prospect_id", "user_id", "policy_id", "uuid", "key"):
                if fallback in live_item:
                    return live_item[fallback]

        return None

    @classmethod
    def _scan_workspace_seeds(cls, workspace_path: str, endpoint: str) -> Optional[Dict[str, Any]]:
        """Scans seed files, SQL dumps, or JSON fixtures in the repository for realistic sample records."""
        try:
            ws = Path(workspace_path)
            if not ws.is_dir():
                return None

            slug = endpoint.strip("/").split("/")[0].rstrip("s")
            # Search for json fixtures or seed files
            seed_files = list(ws.glob("**/*seed*.*")) + list(ws.glob("**/fixtures/*.*")) + list(ws.glob("**/*mock*.*"))
            for sf in seed_files[:10]:
                if sf.suffix.lower() == ".json":
                    try:
                        content = json.loads(sf.read_text(encoding="utf-8", errors="ignore"))
                        item = cls._extract_first_item(content)
                        if item:
                            return item
                    except Exception:
                        pass
        except Exception:
            pass
        return None
