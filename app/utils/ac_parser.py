import re
from typing import List, Dict, Any, Tuple


def extract_clean_acceptance_criteria(story_title: str, description: str, db_acs: List[Any] = None) -> List[Dict[str, Any]]:
    """
    Intelligently parses, filters, and normalizes Acceptance Criteria from a User Story.
    Preserves all explicit Acceptance Criteria provided by the user while standardizing keys (AC-01, AC-02, ...).
    """
    if db_acs and len(db_acs) > 0:
        cleaned = []
        for item in db_acs:
            if isinstance(item, dict):
                text = (item.get("text") or item.get("requirement") or "").strip()
            else:
                text = str(item).strip()

            if text and len(text) >= 3:
                cleaned.append(text)
        if cleaned:
            return _normalize_and_deduplicate_acs(cleaned, story_title)

    desc = (description or "").strip()
    if not desc:
        return _generate_fallback_acs(story_title)

    raw_lines = [l.strip() for l in desc.split("\n") if l.strip()]
    merged_items = []
    pending_header = ""

    for line in raw_lines:
        if line.startswith("---") or line.startswith("===") or len(line) < 3:
            continue

        if _is_ignorable_line(line, story_title):
            continue

        is_header = _is_section_header(line)

        if is_header:
            pending_header = _clean_ac_line(line)
        else:
            clean_line = _clean_ac_line(line)
            if clean_line:
                if pending_header:
                    header_label = pending_header.rstrip(":")
                    if header_label.lower() not in clean_line.lower():
                        combined = f"{header_label}: {clean_line}"
                    else:
                        combined = clean_line
                    merged_items.append(combined)
                    pending_header = ""
                else:
                    merged_items.append(clean_line)

    if pending_header and not merged_items:
        merged_items.append(pending_header)

    if not merged_items:
        return _generate_fallback_acs(story_title)

    return _normalize_and_deduplicate_acs(merged_items, story_title)


def _clean_ac_line(line: str) -> str:
    """Strips markdown bullets, numbering, and duplicate 'AC 1:', 'Acceptance Criterion 2:' prefixes."""
    clean = re.sub(r"^[#\*\-•0-9\.\s]+", "", line).strip()
    # Strip prefixes like "AC 1:", "AC-01:", "AC#1:", "Acceptance Criteria 1:", "Acceptance Criterion 1:"
    clean = re.sub(r"^(?:AC|Acceptance\s*Criteri(?:a|on))[\s\-_\#]*\d*[\s:\.-]+", "", clean, flags=re.IGNORECASE).strip()
    return clean


def _is_ignorable_line(line: str, story_title: str) -> bool:
    """Checks if line is persona, narrative metadata, or story title rather than an acceptance criterion."""
    low = line.lower().strip()
    clean_title = (story_title or "").lower().strip()

    # Exact match only to the full title line
    if clean_title and low == clean_title:
        return True

    # Check for Persona or User Story Narrative patterns
    # e.g., "As an Agent (System User)", "As a user", "As the admin", "I want to...", "So that..."
    if re.match(r"^as\s+(?:a|an|the|any)\s+", low) or low.startswith("as an ") or low.startswith("as a "):
        return True
    if re.match(r"^i\s+(?:want|need|wish)\s+to\s+", low):
        return True
    if re.match(r"^so\s+that\s+", low) or re.match(r"^in\s+order\s+to\s+", low):
        return True

    # Common non-requirement headers
    if (low.startswith("title:") or
        low.startswith("user story:") or
        low.startswith("story:") or
        low.startswith("description:") or
        low.startswith("sprint:") or
        low.startswith("epic:") or
        low == "acceptance criteria:" or
        low == "acceptance criteria" or
        low.startswith("context:") or
        low.startswith("notes:")):
        return True

    return False


def _is_section_header(line: str) -> bool:
    """Detects short section headers like 'POST API (Fetch Specific Prospect Details)'."""
    clean = _clean_ac_line(line)
    if len(clean) < 80:
        if any(v in clean.upper() for v in ("POST API", "GET API", "PUT API", "DELETE API", "PATCH API", "ENDPOINT:", "API:")):
            return True
        if re.match(r"^(GET|POST|PUT|DELETE|PATCH)\s+[/a-zA-Z0-9_\-]+(\s*\(.*\))?$", clean, re.IGNORECASE):
            return True
        if line.strip().startswith("###") or line.strip().startswith("##"):
            return True
    return False


def infer_endpoint_from_ac(ac_text: str, story_title: str = "") -> Tuple[str, str]:
    """Infers HTTP method and explicit REST path from an Acceptance Criterion text if specified."""
    low = ac_text.lower()
    method = "GET"
    if "post " in low or "post api" in low or "create " in low or "register " in low or "add " in low or "insert " in low:
        method = "POST"
    elif "delete " in low or "delete api" in low or "remove " in low or "cancel " in low:
        method = "DELETE"
    elif "put " in low or "put api" in low or "update " in low or "replace " in low:
        method = "PUT"
    elif "patch " in low or "patch api" in low or "modify " in low:
        method = "PATCH"

    # 1. Check for explicit path like /api/... or /auth/... or /v1/...
    m = re.search(r"(/api/[a-zA-Z0-9_\-\/{}\.]+|/v\d+/[a-zA-Z0-9_\-\/{}\.]+|/[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\/{}\.]+)", ac_text)
    if m:
        path = m.group(1).rstrip(".")
        if len(path) > 2:
            return method, path

    # 2. Check in story title for explicit path
    if story_title:
        m_title = re.search(r"(/api/[a-zA-Z0-9_\-\/{}\.]+|/v\d+/[a-zA-Z0-9_\-\/{}\.]+|/[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\/{}\.]+)", story_title)
        if m_title:
            path = m_title.group(1).rstrip(".")
            if len(path) > 2:
                return method, path

    return method, None


def _normalize_and_deduplicate_acs(items: List[str], story_title: str) -> List[Dict[str, Any]]:
    """Deduplicates, formats, and assigns clean AC-01, AC-02, ... keys."""
    seen_texts = set()
    unique_items = []

    for item in items:
        cleaned = " ".join(item.split()).strip()
        cleaned = _clean_ac_line(cleaned)
        if len(cleaned) < 5:
            continue

        normalized_key = cleaned.lower()[:60]
        if normalized_key not in seen_texts:
            seen_texts.add(normalized_key)
            unique_items.append(cleaned)

    if not unique_items:
        return _generate_fallback_acs(story_title)

    result = []
    for idx, text in enumerate(unique_items, start=1):
        ac_key = f"AC-{idx:02d}"
        method, path = infer_endpoint_from_ac(text, story_title)
        result.append({
            "ac_key": ac_key,
            "text": text,
            "requirement": text,
            "inferred_method": method,
            "inferred_path": path
        })

    return result


def _generate_fallback_acs(story_title: str) -> List[Dict[str, Any]]:
    """Generates standard REST criteria when no description is supplied."""
    entity = "resource"
    title_words = [w for w in (story_title or "").split() if len(w) > 2]
    if title_words:
        entity = title_words[-1].lower().rstrip("s")

    return [
        {"ac_key": "AC-01", "text": f"Create {entity} via POST /api/{entity}s with valid schema returns 201 Created", "requirement": f"Create {entity}", "inferred_method": "POST", "inferred_path": f"/api/{entity}s"},
        {"ac_key": "AC-02", "text": f"Retrieve {entity} details by ID via GET /api/{entity}s/{{id}} returns 200 OK", "requirement": f"Get {entity} by ID", "inferred_method": "GET", "inferred_path": f"/api/{entity}s/{{id}}"},
        {"ac_key": "AC-03", "text": f"Retrieve list of all {entity}s via GET /api/{entity}s returns 200 OK array", "requirement": f"List {entity}s", "inferred_method": "GET", "inferred_path": f"/api/{entity}s"},
        {"ac_key": "AC-04", "text": f"Delete {entity} by ID via DELETE /api/{entity}s/{{id}} returns 200 OK or 204 No Content", "requirement": f"Delete {entity}", "inferred_method": "DELETE", "inferred_path": f"/api/{entity}s/{{id}}"},
        {"ac_key": "AC-05", "text": f"Submitting invalid payload or non-existent ID returns appropriate 4xx error (400/404/422)", "requirement": "Validation & Error Handling", "inferred_method": "POST", "inferred_path": f"/api/{entity}s"}
    ]

