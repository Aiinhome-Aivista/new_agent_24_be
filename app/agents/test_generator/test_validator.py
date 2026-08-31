"""Test Case Deduplication, Acceptance Criteria Coverage Validator, Grounding Validator, and Contract Gap Detection."""
import re
from typing import List, Dict, Any, Tuple


class TestCaseDeduplicator:
    """Deduplicates test scenarios based on specific test intent, boundary condition, and AC mapping."""

    @staticmethod
    def _normalize_text(text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
        return " ".join(cleaned.split())

    @staticmethod
    def _extract_intent_signature(tc: Dict[str, Any]) -> str:
        """Extracts a fine-grained intent signature so separate boundary/validation cases are NOT falsely merged."""
        title = (tc.get("title") or "").lower()
        desc = (tc.get("description") or "").lower()
        combined = f"{title} {desc}"
        stype = (tc.get("scenario_type") or "positive").lower()

        # Extract AC key (e.g. AC-01, AC-02, etc.)
        ac_ids = tc.get("acceptance_criteria_ids") or []
        primary_ac = ac_ids[0] if ac_ids else "AC-GEN"

        # Identify specific fine-grained scenario conditions
        condition = "general"
        if "incorrect current" in combined or "wrong current" in combined or "current password" in combined and "incorrect" in combined:
            condition = "incorrect_current_pwd"
        elif "multiple rule" in combined or "multi rule" in combined or "multiple failure" in combined or "multiple violation" in combined:
            condition = "pwd_multiple_rule_failures"
        elif "exactly 8" in combined or "exact 8" in combined or "8 char" in combined and ("compliant" in combined or "valid" in combined):
            condition = "pwd_len_exact_8"
        elif "shorter than 8" in combined or "min 8" in combined or "< 8" in combined or "below 8" in combined or "7 char" in combined or "short" in combined or "length" in combined:
            condition = "pwd_len_under_8"
        elif "special" in combined or "symbol" in combined or "non-alphanumeric" in combined:
            condition = "pwd_missing_special"
        elif "number" in combined or "digit" in combined or "numeric" in combined:
            condition = "pwd_missing_number"
        elif "previous jwt" in combined or "old jwt" in combined or "token invalidation" in combined or "invalidated jwt" in combined or "invalidation" in combined:
            condition = "jwt_invalidation_after_change"
        elif "missing jwt" in combined or "without jwt" in combined or "no jwt" in combined or "no token" in combined or "missing authorization" in combined or "unauthenticated" in combined:
            condition = "auth_missing_jwt"
        elif "invalid jwt" in combined or "tampered jwt" in combined or "malformed jwt" in combined or "expired jwt" in combined:
            condition = "auth_invalid_jwt"
        elif "leak" in combined or "not exposed" in combined or "never include" in combined or "plaintext" in combined or "hash exposure" in combined or "exposure" in combined:
            condition = "security_no_pwd_hash_leakage"
        elif "valid" in combined and ("success" in combined or "allow" in combined or "proceed" in combined):
            condition = "happy_path_success"

        return f"{primary_ac}::{stype}::{condition}"

    @classmethod
    def deduplicate(cls, test_cases: List[Dict[str, Any]], story_key: str = "SBP101") -> List[Dict[str, Any]]:
        """Removes true duplicates while preserving all distinct boundary, validation, and security scenarios."""
        if not test_cases:
            return []

        clean_key = re.sub(r"[^a-zA-Z0-9]", "", story_key).upper() or "TC"
        deduped: List[Dict[str, Any]] = []
        seen_signatures = set()

        for tc in test_cases:
            req = tc.get("request_spec") or {}
            endpoint = (req.get("endpoint") or "").lower().rstrip("/")
            sig = f"{endpoint}::{cls._extract_intent_signature(tc)}"

            # If signature is already seen and has a specific condition, treat as duplicate
            if sig in seen_signatures:
                continue

            seen_signatures.add(sig)
            deduped.append(tc)

        # Assign deterministic, sequential test keys
        for idx, tc in enumerate(deduped, start=1):
            tc["test_key"] = f"TC-{clean_key}-{idx:03d}"

        return deduped


class AcceptanceCriteriaCoverageValidator:
    """Validates that EVERY Acceptance Criterion in the story has at least one mapped test case."""

    @staticmethod
    def _normalize_ac_key(ac_item: Any, idx: int) -> Tuple[str, str]:
        """Extracts standard AC key (e.g. AC-01) and text requirement."""
        if isinstance(ac_item, dict):
            key = ac_item.get("ac_key") or f"AC-{idx:02d}"
            text = ac_item.get("text") or str(ac_item)
        else:
            text = str(ac_item)
            match = re.match(r"^(AC[-\s]?\d+)\s*[:\.-]?\s*(.*)", text, re.IGNORECASE)
            if match:
                key = match.group(1).upper().replace(" ", "-")
                if not re.match(r"^AC-\d{2,}$", key):
                    # Normalize AC-1 to AC-01
                    num_part = re.sub(r"[^0-9]", "", key)
                    key = f"AC-{int(num_part):02d}"
                text = match.group(2)
            else:
                key = f"AC-{idx:02d}"
        return key, text

    @classmethod
    def validate_coverage(cls, test_cases: List[Dict[str, Any]], acceptance_criteria: List[Any]) -> Dict[str, Any]:
        """Generates an AC Coverage Matrix and verifies 100% AC coverage."""
        matrix = []
        covered_count = 0
        missing_acs = []

        # Build lookup of covered AC keys from test cases
        ac_to_tests: Dict[str, List[str]] = {}
        for tc in test_cases:
            t_key = tc.get("test_key", "TC-UNKNOWN")
            ac_ids = tc.get("acceptance_criteria_ids") or []
            story_ref = tc.get("story_reference") or ""

            # Check explicit AC IDs
            for ac_id in ac_ids:
                norm_id = ac_id.upper().strip()
                if re.match(r"^AC-\d$", norm_id):
                    norm_id = f"AC-{int(norm_id[3:]):02d}"
                ac_to_tests.setdefault(norm_id, []).append(t_key)

            # Check story reference string (e.g. "AC-01: ...")
            ref_matches = re.findall(r"AC[-_\s]?(\d+)", story_ref, re.IGNORECASE)
            for m in ref_matches:
                norm_id = f"AC-{int(m):02d}"
                if t_key not in ac_to_tests.setdefault(norm_id, []):
                    ac_to_tests[norm_id].append(t_key)

        for idx, raw_ac in enumerate(acceptance_criteria, start=1):
            ac_key, ac_text = cls._normalize_ac_key(raw_ac, idx)
            mapped_tcs = ac_to_tests.get(ac_key, [])
            is_covered = len(mapped_tcs) > 0

            if is_covered:
                covered_count += 1
            else:
                missing_acs.append(ac_key)

            # Short concise requirement summary
            req_summary = ac_text.split(",")[0] if "," in ac_text else ac_text[:80]
            req_summary = req_summary.replace("Given ", "").replace("When ", "")

            matrix.append({
                "ac_key": ac_key,
                "requirement": req_summary.strip(),
                "full_text": ac_text,
                "covered": is_covered,
                "test_case_keys": mapped_tcs
            })

        total_acs = len(acceptance_criteria)
        coverage_pct = round((covered_count / total_acs * 100), 1) if total_acs > 0 else 100.0

        return {
            "coverage_complete": len(missing_acs) == 0,
            "total_acceptance_criteria": total_acs,
            "covered_acceptance_criteria": covered_count,
            "coverage_pct": coverage_pct,
            "missing_acceptance_criteria": missing_acs,
            "coverage_matrix": matrix
        }


class GenerationSummaryCalculator:
    """Calculates non-fabricated, real QA generation quality metrics."""

    @staticmethod
    def calculate(total_candidates: int,
                  final_test_cases: List[Dict[str, Any]],
                  coverage_report: Dict[str, Any],
                  contract_gaps: List[Dict[str, Any]]) -> Dict[str, Any]:
        final_count = len(final_test_cases)
        duplicates_removed = max(0, total_candidates - final_count)

        confirmed_count = sum(1 for tc in final_test_cases if tc.get("grounding_metadata", {}).get("overall_grounding") == "CONFIRMED")
        partially_confirmed_count = sum(1 for tc in final_test_cases if tc.get("grounding_metadata", {}).get("overall_grounding") == "PARTIALLY_CONFIRMED")
        needs_review_count = sum(1 for tc in final_test_cases if tc.get("requires_review") or tc.get("grounding_metadata", {}).get("overall_grounding") == "NEEDS_REVIEW")

        return {
            "total_candidates": total_candidates,
            "duplicates_removed": duplicates_removed,
            "final_unique_test_cases": final_count,
            "acceptance_criteria_total": coverage_report.get("total_acceptance_criteria", 0),
            "acceptance_criteria_covered": coverage_report.get("covered_acceptance_criteria", 0),
            "coverage_pct": coverage_report.get("coverage_pct", 0.0),
            "coverage_complete": coverage_report.get("coverage_complete", False),
            "missing_acceptance_criteria": coverage_report.get("missing_acceptance_criteria", []),
            "grounding_confirmed": confirmed_count,
            "grounding_partially_confirmed": partially_confirmed_count,
            "needs_review": needs_review_count,
            "contract_gaps": len(contract_gaps)
        }


class TestCaseValidator:
    """Validates test case integrity, source grounding, and ensures no fabricated results."""

    ALLOWED_SOURCES = {
        "STORY",
        "ACCEPTANCE_CRITERIA",
        "API_CONTRACT",
        "CONTRACT_SPECIFIED",
        "POSTMAN",
        "PROJECT_KB",
        "CODEBASE",
        "GLOBAL_KB",
        "AI_DERIVED",
        "AI_ASSUMPTION",
        "UNKNOWN",
    }

    @classmethod
    def evaluate_overall_grounding(cls, tc: Dict[str, Any]) -> str:
        """Accurately classifies overall grounding level without over-claiming CONFIRMED."""
        if tc.get("requires_review") or tc.get("expected_response_spec", {}).get("status_source") == "AI_ASSUMPTION":
            return "NEEDS_REVIEW"

        status_src = tc.get("expected_response_spec", {}).get("status_source")
        endpoint_src = tc.get("grounding_metadata", {}).get("endpoint", {}).get("source")
        res_body_src = tc.get("expected_response_spec", {}).get("response_body_source") or tc.get("grounding_metadata", {}).get("response_body", {}).get("source")

        if status_src in ("ACCEPTANCE_CRITERIA", "API_CONTRACT", "STORY") and endpoint_src in ("STORY", "API_CONTRACT"):
            if res_body_src in ("ACCEPTANCE_CRITERIA", "API_CONTRACT"):
                return "CONFIRMED"
            # If status and endpoint are grounded, but response body schema is unknown/not defined in source
            return "PARTIALLY_CONFIRMED"

        return "AI_DERIVED"

    @classmethod
    def validate_test_case(cls, tc: Dict[str, Any], story: Dict[str, Any], contracts: List[Dict[str, Any]], has_codebase: bool = False) -> Tuple[bool, List[str]]:
        errors = []

        # 1. Key validation
        key = tc.get("test_key", "")
        if not key or not re.match(r"^TC-[A-Z0-9]+-\d{3}$", key):
            errors.append(f"Invalid test_key format '{key}'. Must match TC-{{STORY_KEY}}-{{SEQ}}.")

        # 2. Title and description validation
        if not tc.get("title") or len(tc.get("title", "").strip()) < 5:
            errors.append("Test case title must be non-empty and descriptive.")

        # 3. Test Type validation
        test_type = tc.get("test_type", "API").upper()
        if test_type not in ("API", "UNIT", "INTEGRATION"):
            errors.append(f"Invalid test_type '{test_type}'. Must be API, UNIT, or INTEGRATION.")

        # 4. Actual execution pollution check
        for forbidden_field in ("actual_result", "execution_status", "defect_id"):
            if tc.get(forbidden_field) is not None:
                errors.append(f"Execution field '{forbidden_field}' must not be populated before test execution.")

        # 5. Source grounding check
        res_spec = tc.get("expected_response_spec") or {}
        status_source = res_spec.get("status_source")
        if status_source and status_source not in cls.ALLOWED_SOURCES:
            errors.append(f"Invalid status_source '{status_source}'.")

        # If status is an AI assumption, requires_review must be true
        if status_source == "AI_ASSUMPTION":
            if not tc.get("requires_review"):
                tc["requires_review"] = True
            if not tc.get("assumption_details"):
                tc["assumption_details"] = "Status code was inferred by AI and requires human review."

        # 6. Responsible functions validation: if no codebase context, must be null
        if not has_codebase:
            tc["responsible_functions"] = None
            tc["responsible_functions_source"] = "UNKNOWN"

        # 7. Test data source tag
        if tc.get("test_data") and not tc.get("test_data_source"):
            tc["test_data_source"] = "AI_DERIVED"

        # 8. Re-evaluate overall grounding
        overall = cls.evaluate_overall_grounding(tc)
        tc.setdefault("grounding_metadata", {})["overall_grounding"] = overall

        return len(errors) == 0, errors


class ContractGapDetector:
    """Detects when an endpoint required by a story is missing from uploaded Postman/API collections."""

    @staticmethod
    def detect_gaps(story: Dict[str, Any], acs: List[str], contracts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        gaps = []
        story_text = f"{story.get('title', '')} {story.get('description', '')} {' '.join(acs or [])}"

        endpoint_matches = re.findall(r"(GET|POST|PUT|DELETE|PATCH)\s+([/a-zA-Z0-9_{}-]+)", story_text)
        distinct_endpoints = list(dict.fromkeys(endpoint_matches))

        uploaded_endpoints = set()
        for c in (contracts or []):
            m = c.get("method", "GET").upper()
            p = c.get("path", "").rstrip("/")
            uploaded_endpoints.add(f"{m} {p}")

        for method, path in distinct_endpoints:
            clean_path = path.rstrip("/")

            match_found = False
            for up in uploaded_endpoints:
                if clean_path in up or up.endswith(clean_path):
                    match_found = True
                    break

            if not match_found and uploaded_endpoints:
                gaps.append({
                    "method": method.upper(),
                    "endpoint": clean_path,
                    "status": "NOT_FOUND_IN_UPLOADED_COLLECTION",
                    "warning": f"Story defines endpoint {method.upper()} {clean_path}, but no matching request/response contract was found in the uploaded Postman/API collection."
                })

        return gaps
