"""
Story Document Extractor — Multi-format parser for user stories, requirements documents,
engagement letters, technical specifications, and Jira exports (.docx, .md, .txt, .json, .pdf).

Extracts:
1. Story Title (clean human-readable title)
2. External Key (e.g. SBP-101, ENG-101)
3. Sprint / Milestone (e.g. Sprint 1, Phase 1)
4. Description / Business Narrative / Scope
5. Acceptance Criteria list (from tables, AC sections, Gherkin blocks, numbered lists, or LLM)
"""
import io
import json
import os
import re
from typing import Dict, Any, List, Optional, Tuple


class StoryDocumentExtractor:
    """
    Robust multi-layer extractor that converts uploaded files into structured user stories
    with comprehensive Acceptance Criteria.
    """

    @classmethod
    def extract_from_file(cls, file_data: Any, filename: str, use_llm: bool = True) -> Dict[str, Any]:
        # 1. Read bytes from various input types (Flask FileStorage, bytes, BytesIO, or path)
        content_bytes = cls._get_bytes(file_data)
        ext = os.path.splitext(filename or "")[1].lower()

        # 2. Extract text, document metadata, and tabular data
        extracted_text, tables, doc_properties = cls._parse_raw_content(content_bytes, ext, filename)

        # 3. Layer 1: Attempt LLM-assisted extraction if configured
        if use_llm:
            llm_result = cls._try_llm_extraction(extracted_text, tables, filename)
            if llm_result and llm_result.get("acceptance_criteria"):
                return {
                    **llm_result,
                    "source_type": ext.lstrip("."),
                    "extracted_count": len(llm_result["acceptance_criteria"]),
                    "raw_text_length": len(extracted_text),
                }

        # 4. Layer 2: Deterministic Heuristic Extractor (reliable offline & structured parsing)
        heuristic_result = cls._heuristic_extraction(extracted_text, tables, doc_properties, filename)
        return {
            **heuristic_result,
            "source_type": ext.lstrip("."),
            "extracted_count": len(heuristic_result.get("acceptance_criteria", [])),
            "raw_text_length": len(extracted_text),
        }

    @classmethod
    def _get_bytes(cls, file_data: Any) -> bytes:
        if isinstance(file_data, bytes):
            return file_data
        if hasattr(file_data, "read"):
            pos = None
            if hasattr(file_data, "tell") and hasattr(file_data, "seek"):
                try:
                    pos = file_data.tell()
                except Exception:
                    pass
            content = file_data.read()
            if pos is not None and hasattr(file_data, "seek"):
                try:
                    file_data.seek(pos)
                except Exception:
                    pass
            return content
        if isinstance(file_data, str) and os.path.isfile(file_data):
            with open(file_data, "rb") as f:
                return f.read()
        return b""

    @classmethod
    def _parse_raw_content(
        cls, content_bytes: bytes, ext: str, filename: str
    ) -> Tuple[str, List[List[List[str]]], Dict[str, str]]:
        """
        Parses document bytes into (full_text, list_of_tables, properties).
        For .docx, parses both paragraphs and tables!
        """
        tables: List[List[List[str]]] = []
        doc_properties: Dict[str, str] = {}
        lines: List[str] = []

        if ext == ".docx":
            try:
                import docx
                doc = docx.Document(io.BytesIO(content_bytes))

                # Core document properties (title, author, subject)
                if hasattr(doc, "core_properties"):
                    props = doc.core_properties
                    if props.title and props.title.strip():
                        doc_properties["title"] = props.title.strip()
                    if hasattr(props, "subject") and props.subject:
                        doc_properties["subject"] = props.subject.strip()

                # Paragraphs extraction
                for p in doc.paragraphs:
                    text = p.text.strip()
                    if text:
                        style_name = (p.style.name if p.style else "").lower()
                        if "title" in style_name or "heading 1" in style_name:
                            lines.append(f"# {text}")
                        elif "heading 2" in style_name:
                            lines.append(f"## {text}")
                        elif "heading 3" in style_name or "heading 4" in style_name:
                            lines.append(f"### {text}")
                        elif "bullet" in style_name or "list" in style_name:
                            lines.append(f"- {text}")
                        else:
                            lines.append(text)

                # Tables extraction (Crucial for Engagement Letters, SOWs, and AC matrices)
                for table in doc.tables:
                    table_rows: List[List[str]] = []
                    lines.append("\n[TABLE START]")
                    for row in table.rows:
                        row_cells = [cell.text.replace("\n", " ").strip() for cell in row.cells]
                        # Remove consecutive identical merged cell texts
                        deduped_cells = []
                        for c in row_cells:
                            if not deduped_cells or c != deduped_cells[-1]:
                                deduped_cells.append(c)
                        if any(c for c in deduped_cells):
                            table_rows.append(deduped_cells)
                            lines.append(" | ".join(deduped_cells))
                    lines.append("[TABLE END]\n")
                    if table_rows:
                        tables.append(table_rows)

                full_text = "\n".join(lines).strip()
                return full_text, tables, doc_properties
            except Exception as e:
                # Fallback if docx reading fails
                text_fallback = content_bytes.decode("utf-8", errors="ignore")
                return text_fallback, [], {}

        elif ext == ".json":
            try:
                parsed = json.loads(content_bytes.decode("utf-8", errors="replace"))
                if isinstance(parsed, dict):
                    full_text = json.dumps(parsed, indent=2)
                    return full_text, [], parsed
            except Exception:
                pass
            return content_bytes.decode("utf-8", errors="replace"), [], {}

        elif ext == ".pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(io.BytesIO(content_bytes))
                text_pages = [page.extract_text() or "" for page in reader.pages]
                return "\n\n".join(text_pages), [], {}
            except Exception:
                pass
            return content_bytes.decode("utf-8", errors="replace"), [], {}

        else:
            # .md, .txt or other text
            try:
                return content_bytes.decode("utf-8"), [], {}
            except UnicodeDecodeError:
                return content_bytes.decode("latin-1", errors="replace"), [], {}

    @classmethod
    def _try_llm_extraction(
        cls, full_text: str, tables: List[List[List[str]]], filename: str
    ) -> Optional[Dict[str, Any]]:
        """
        Uses Gemini or configured LLM client to parse the text into structured JSON.
        """
        if not full_text or len(full_text.strip()) < 15:
            return None

        try:
            from app.llm.client.gemini_client import build_client
            client = build_client()
            if hasattr(client, "_mock") or "mock" in getattr(client, "default_model", "").lower():
                # Don't rely on mock LLM for real extraction
                if getattr(client, "__class__", None).__name__ == "MockGeminiClient":
                    return None

            prompt_doc = full_text[:12000]

            system_instruction = (
                "You are an expert QA Architect and Business Analyst.\n"
                "Your task is to analyze the provided document (which may be a User Story, Technical Specification, "
                "Business Requirements Document, Engagement Letter, Statement of Work, or Timeline Agreement) "
                "and extract structured user story fields for automated TDD test generation.\n\n"
                "Extraction Guidelines:\n"
                "1. 'title': Clear, concise story or document title without garbage symbols.\n"
                "2. 'external_key': Jira/Story issue key (e.g. SBP-101, ENG-101, PROJ-10) or null.\n"
                "3. 'sprint': Sprint name, milestone, or timeline phase (e.g. 'Sprint 1', 'Phase 1 - Kickoff').\n"
                "4. 'description': Comprehensive business narrative/context or user story ('As a... I want... So that...').\n"
                "5. 'acceptance_criteria': Array of discrete, testable acceptance criteria, deliverables, requirements, "
                "or timeline commitments. Each item must have 'ac_key' ('AC-1', 'AC-2', ...) and 'text' with the rule/deliverable.\n\n"
                "Return strictly valid JSON matching this schema:\n"
                "{\n"
                '  "title": "string",\n'
                '  "external_key": "string or null",\n'
                '  "sprint": "string",\n'
                '  "description": "string",\n'
                '  "acceptance_criteria": [\n'
                '    {"ac_key": "AC-1", "text": "Specific testable condition or requirement..."}\n'
                "  ]\n"
                "}"
            )

            user_prompt = f"Filename: {filename}\n\nDocument Content:\n{prompt_doc}"

            result = client.generate(
                model=None,
                system=system_instruction,
                prompt=user_prompt,
                temperature=0.1,
                max_tokens=2048,
                as_json=True,
            )

            if result and result.text and not result.is_mock:
                cleaned_json = result.text.strip()
                if cleaned_json.startswith("```json"):
                    cleaned_json = cleaned_json[7:]
                elif cleaned_json.startswith("```"):
                    cleaned_json = cleaned_json[3:]
                if cleaned_json.endswith("```"):
                    cleaned_json = cleaned_json[:-3]
                cleaned_json = cleaned_json.strip()

                parsed = json.loads(cleaned_json)
                if isinstance(parsed, dict) and parsed.get("acceptance_criteria"):
                    # Normalize acceptance criteria keys
                    acs = []
                    for i, item in enumerate(parsed["acceptance_criteria"], start=1):
                        txt = (item.get("text") if isinstance(item, dict) else str(item)).strip()
                        if txt and len(txt) > 5:
                            acs.append({"ac_key": f"AC-{i}", "text": txt})

                    if acs:
                        return {
                            "title": (parsed.get("title") or cls._clean_filename_title(filename)).strip(),
                            "external_key": (parsed.get("external_key") or "").strip(),
                            "sprint": (parsed.get("sprint") or "Sprint 1").strip(),
                            "description": (parsed.get("description") or "").strip(),
                            "acceptance_criteria": acs,
                        }
        except Exception as e:
            # Fall back to heuristic extraction seamlessly
            print(f"[StoryExtractor] LLM extraction skipped or encountered error: {e}")

        return None

    @classmethod
    def _heuristic_extraction(
        cls,
        text: str,
        tables: List[List[List[str]]],
        doc_properties: Dict[str, str],
        filename: str,
    ) -> Dict[str, Any]:
        """
        Deterministic, rule-based extraction that guarantees structured results
        even without LLMs or Internet connectivity.
        """
        clean_text = cls._clean_text_string(text)
        lines = [l.strip() for l in clean_text.split("\n") if l.strip()]

        # 1. EXTRACT TITLE
        title = ""
        # A. From docx properties
        if doc_properties.get("title") and len(doc_properties["title"]) > 3:
            title = doc_properties["title"].strip()

        # B. From first heading line (# Title)
        if not title:
            for l in lines:
                if l.startswith("# ") and len(l) > 4:
                    title = l.replace("# ", "").strip()
                    # Strip bracketed key if present e.g. # [SBP-101] Change Password
                    title = re.sub(r"^\[[^\]]+\]\s*", "", title)
                    break
                elif re.match(r"^(?:Title|User Story|Story|Document|Engagement Letter)[:\-]\s*(.+)", l, re.I):
                    m = re.match(r"^(?:Title|User Story|Story|Document|Engagement Letter)[:\-]\s*(.+)", l, re.I)
                    if m:
                        title = m.group(1).strip()
                        break

        # C. First short, non-bullet, non-table line
        if not title:
            for l in lines[:10]:
                if not l.startswith("[") and not l.startswith("|") and not l.startswith("-") and 4 < len(l) < 90:
                    # Ignore date lines or page numbers
                    if not re.match(r"^(Date|Version|Page|Author|Confidential)[:\s]", l, re.I):
                        title = l.strip()
                        break

        # D. Clean filename fallback
        if not title or len(title) < 3 or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", title):
            title = cls._clean_filename_title(filename)

        # 2. EXTRACT EXTERNAL KEY
        external_key = ""
        # Search for pattern like [SBP-101] or Key: SBP-101 or SBP-101 in first 50 lines
        key_match = (
            re.search(r"\[([A-Z]{2,10}-\d+)\]", clean_text)
            or re.search(r"(?:Key|Jira|Ticket|Story\s*ID)[:\s]+([A-Za-z0-9_-]+)", clean_text, re.I)
            or re.search(r"\b([A-Z]{2,8}-\d{2,6})\b", clean_text)
        )
        if key_match:
            external_key = key_match.group(1).strip()

        # 3. EXTRACT SPRINT / MILESTONE
        sprint = "Sprint 1"
        sprint_match = (
            re.search(r"(?:Sprint|Milestone|Phase|Release)[:\s]+([^\r\n|]+)", clean_text, re.I)
            or re.search(r"\|\s*\*\*Sprint\*\*\s*\|\s*([^|\r\n]+)\|", clean_text, re.I)
        )
        if sprint_match:
            candidate = sprint_match.group(1).strip()
            if 2 < len(candidate) < 50:
                sprint = candidate

        # 4. EXTRACT ACCEPTANCE CRITERIA
        found_criteria: List[str] = []

        # Source A: Tables (Extract rows from criteria / requirement / deliverable / timeline tables)
        for table in tables:
            if not table or len(table) < 2:
                continue
            headers = [c.lower() for c in table[0]]
            
            # Find prefix/ID columns (e.g. Milestone, Task ID, AC #)
            prefix_col_indices = [
                i for i, h in enumerate(headers)
                if any(kw in h for kw in ["milestone", "phase", "id", "item", "key", "number", "no.", "code"])
            ]
            # Find core criteria/requirement columns
            crit_col_indices = [
                i for i, h in enumerate(headers)
                if any(kw in h for kw in [
                    "criteria", "acceptance", "requirement", "scenario", "deliverable",
                    "condition", "task", "action", "description", "scope"
                ])
            ]

            # If specific criteria columns exist, extract from each row
            if crit_col_indices:
                for row in table[1:]:
                    prefix_str = ""
                    if prefix_col_indices:
                        p_idx = prefix_col_indices[0]
                        if p_idx < len(row) and row[p_idx].strip() and not cls._is_header_or_noise(row[p_idx]):
                            prefix_str = row[p_idx].strip()

                    for i in crit_col_indices:
                        if i < len(row) and row[i].strip() and not cls._is_header_or_noise(row[i]):
                            text_val = row[i].strip()
                            if prefix_str and not text_val.startswith(f"[{prefix_str}]") and prefix_str not in text_val:
                                text_val = f"[{prefix_str}] {text_val}"
                            if len(text_val) > 6:
                                found_criteria.append(text_val)
            else:
                # If table contains a status/date/deliverable matrix, extract formatted row
                for row in table[1:]:
                    joined = " — ".join([c for c in row if c.strip() and not cls._is_header_or_noise(c)])
                    if len(joined) > 10:
                        found_criteria.append(joined)

        # Source B: Headed Sections (e.g. ## Acceptance Criteria)
        ac_section_pattern = re.compile(
            r"(?:##?|\*\*)\s*(?:Acceptance Criteria|Conditions of Acceptance|Key Requirements|Deliverables|Milestones|Scope of Work|Validation Rules|Test Scenarios)[^\n]*\n([\s\S]*?)(?=\n(?:##|\*\*|$))",
            re.I,
        )
        for match in ac_section_pattern.finditer(clean_text):
            section_content = match.group(1)
            for line in section_content.split("\n"):
                l = line.strip()
                # Bullet or numbered item
                bullet_m = re.match(r"^(?:[-*•]|\d+\.|\(?[a-z]\)|AC[-\s]?\d+[:.-]?)\s*(.+)", l, re.I)
                if bullet_m:
                    item_text = bullet_m.group(1).strip()
                    if len(item_text) > 6 and not cls._is_header_or_noise(item_text):
                        found_criteria.append(item_text)
                elif l.lower().startswith("given ") or l.lower().startswith("when ") or l.lower().startswith("then "):
                    found_criteria.append(l)

        # Source C: Document-wide bullet points, Gherkin blocks, or modal rules
        if len(found_criteria) < 2:
            for l in lines:
                ac_m = re.match(r"^(?:[-*•]|\d+\.|AC[-\s]?\d+[:.-]?)\s*(.+)", l, re.I)
                if ac_m:
                    val = ac_m.group(1).strip()
                    if len(val) > 8 and not cls._is_header_or_noise(val):
                        # Filter out table header fragments
                        if not val.startswith("|") and not val.startswith("["):
                            found_criteria.append(val)
                elif re.match(r"^(Given|When|Then|And)\s+.+", l, re.I):
                    found_criteria.append(l)
                elif any(kw in l.lower() for kw in [" must ", " shall ", " will deliver ", " will provide ", " is required to "]):
                    if 15 < len(l) < 250 and not l.startswith("#"):
                        found_criteria.append(l)

        # Clean and deduplicate criteria
        seen = set()
        deduped_acs: List[Dict[str, str]] = []
        for item in found_criteria:
            cleaned_item = re.sub(r"^\*\*|\*\*$", "", item).strip()
            cleaned_item = re.sub(r"^(?:AC-\d+[:.-]?|AC\s*\d+[:.-]?)\s*", "", cleaned_item, flags=re.I).strip()
            key_hash = cleaned_item.lower()
            if key_hash not in seen and len(cleaned_item) >= 6:
                seen.add(key_hash)
                deduped_acs.append({
                    "ac_key": f"AC-{len(deduped_acs) + 1}",
                    "text": cleaned_item
                })

        # Guarantee at least 2 meaningful criteria if none could be extracted
        if len(deduped_acs) == 0:
            deduped_acs = [
                {
                    "ac_key": "AC-1",
                    "text": f"Verify system fulfills deliverables and requirements specified in {title}."
                },
                {
                    "ac_key": "AC-2",
                    "text": "All endpoints, validations, and responses adhere to contract specifications without unauthorized deviations."
                }
            ]

        # 5. EXTRACT DESCRIPTION / USER STORY NARRATIVE
        desc_match = (
            re.search(r"(?:##?|\*\*)\s*Description[^\n]*\n([\s\S]*?)(?=\n(?:##|\*\*|$))", clean_text, re.I)
            or re.search(r"(?:##?|\*\*)\s*(?:Overview|Scope|Executive Summary|Objective)[^\n]*\n([\s\S]*?)(?=\n(?:##|\*\*|$))", clean_text, re.I)
        )
        description = ""
        if desc_match:
            raw_desc = desc_match.group(1).strip()
            description = "\n".join([
                line.strip() for line in raw_desc.split("\n")
                if not line.strip().startswith("|") and not line.strip().startswith("[")
            ]).strip()

        # Check for standard user story format "As a ... I want ... So that ..."
        story_narrative_match = re.search(r"(As a[^\n]+I want[^\n]+so that[^\n]+)", clean_text, re.I)
        if story_narrative_match:
            narrative = story_narrative_match.group(1).strip()
            if description:
                description = f"{narrative}\n\n{description}"
            else:
                description = narrative

        if not description:
            # Fallback: take first 2-3 clean body paragraphs
            body_paragraphs = [
                l for l in lines
                if not l.startswith("#") and not l.startswith("|") and not l.startswith("[") and len(l) > 30
            ]
            description = "\n\n".join(body_paragraphs[:3]) if body_paragraphs else f"User story specification for {title}."

        return {
            "title": title,
            "external_key": external_key,
            "sprint": sprint,
            "description": description,
            "acceptance_criteria": deduped_acs,
        }

    @classmethod
    def _clean_text_string(cls, text: str) -> str:
        """Removes null bytes and control chars while keeping line breaks."""
        if not text:
            return ""
        # Remove null and non-printable control characters (except \n, \r, \t)
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

    @classmethod
    def _clean_filename_title(cls, filename: str) -> str:
        """Transforms filenames like 'Updated_Engagement_Letter_With_Timeline (1) (1).docx' into clean titles."""
        if not filename:
            return "New User Story"
        base = os.path.splitext(filename)[0]
        # Remove duplicate copy indicators like (1), (2), _copy
        base = re.sub(r"\(\d+\)", "", base)
        base = re.sub(r"[-_]+copy\d*", "", base, flags=re.I)
        # Replace underscores and dashes with spaces
        base = base.replace("_", " ").replace("-", " ")
        # Collapse multiple spaces
        base = re.sub(r"\s+", " ", base).strip()
        # Capitalize nicely
        words = [w.capitalize() if not w.isupper() else w for w in base.split()]
        return " ".join(words) or "New User Story"

    @classmethod
    def _is_header_or_noise(cls, text: str) -> bool:
        """Filters out non-content lines like table headers, dates, or page numbers."""
        lower = text.lower().strip()
        if lower in [
            "acceptance criteria", "criteria", "ac", "requirement", "description",
            "timeline", "milestone", "date", "status", "action", "owner", "table of contents",
            "page", "signature", "confidential", "all rights reserved"
        ]:
            return True
        if re.match(r"^page \d+( of \d+)?$", lower):
            return True
        return False


def extract_story_from_file(file_data: Any, filename: str, use_llm: bool = True) -> Dict[str, Any]:
    """Public helper function."""
    return StoryDocumentExtractor.extract_from_file(file_data, filename, use_llm=use_llm)
