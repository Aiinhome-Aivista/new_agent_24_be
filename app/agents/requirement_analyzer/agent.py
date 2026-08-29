import json
from app.agents.base import BaseAgent
from app.llm.model_router.router import get_router
from app.guardrails.engine import check_input
from app.workflows.state_machine import SERVICE_PLANNING, BLOCKED

# Detailed system prompt for requirement decomposition
_SYSTEM_PROMPT = """You are an expert QA analyst specializing in test scenario decomposition.

Given a user story and its acceptance criteria, decompose the requirements into structured
test scenarios. You MUST return a valid JSON object with the following keys:

{
  "business_rules": [{"id": "BR-1", "desc": "...description of the business rule..."}],
  "positive_scenarios": [{"id": "SCN-P1", "desc": "...happy path scenario description..."}],
  "negative_scenarios": [{"id": "SCN-N1", "desc": "...failure/error scenario description..."}],
  "boundary_scenarios": [{"id": "SCN-B1", "desc": "...edge case / limit scenario description..."}],
  "validation_scenarios": [{"id": "SCN-V1", "desc": "...input validation scenario..."}],
  "error_scenarios": [{"id": "SCN-E1", "desc": "...system error / exception scenario..."}],
  "ambiguities": ["...any unclear or underspecified requirements..."]
}

Rules:
1. NEVER invent requirements not stated or implied in the acceptance criteria.
2. Each scenario MUST trace back to at least one acceptance criterion.
3. Decompose ALL acceptance criteria thoroughly: generate multiple positive, negative, boundary, validation, and security/error scenarios for every single acceptance criterion. For example, a password strength rule (AC-3) must produce separate scenarios for: too short, missing number, missing special character, 7-char boundary, 8-char boundary, and multiple failures. An authentication rule (AC-6) must produce scenarios for: missing token, invalid signature, malformed token, and expired token.
4. Keep scenario descriptions specific, technical, and actionable.
5. If acceptance criteria are vague, list the ambiguity — do NOT guess.
"""


class RequirementAnalyzerAgent(BaseAgent):
    name = "requirement_analyzer"

    def run(self, workflow_id, state):
        story = state.get("story", {})
        acs = state.get("acceptance_criteria", [])
        text = f"{story.get('title', '')} {story.get('description', '')}"

        clean, detail = check_input(text, workflow_id)
        if not clean:
            state["status"] = BLOCKED
            state.setdefault("errors", []).append({"agent": self.name, "message": detail})
            return state

        if not acs:
            # Never invent missing rules — flag clarification.
            state["clarification_required"] = True
            state.setdefault("errors", []).append(
                {"agent": self.name, "message": "No acceptance criteria — clarification required."})
            state["status"] = BLOCKED
            self._record(workflow_id, "requirement_analysis", status="BLOCKED")
            return state

        print(f"\n[RequirementAnalyzer] Story: '{story.get('title', '')}' (Key: {story.get('external_key', 'N/A')})")
        print(f"[RequirementAnalyzer] Decomposing {len(acs)} Acceptance Criteria:")
        for idx, ac in enumerate(acs, start=1):
            ac_preview = (ac[:80] + "...") if len(ac) > 80 else ac
            print(f"   • AC-{idx}: {ac_preview}")

        # Retrieve RAG context if available
        rag_context = self._get_rag_context(state, text)
        if rag_context:
            print(f"[RequirementAnalyzer] Injected {len(rag_context)} chars of RAG knowledge context.")

        # Build a rich prompt with story details, acceptance criteria, and RAG context
        ac_text = "\n".join(f"  - AC-{i+1}: {ac}" for i, ac in enumerate(acs))
        prompt = f"""User Story: {story.get('title', '')}

Description:
{story.get('description', 'No description provided.')}

Acceptance Criteria:
{ac_text}
"""
        if rag_context:
            prompt += f"\nProject Context (from knowledge base):\n{rag_context}\n"

        # Call Gemini for structured analysis
        router = get_router()
        print(f"[RequirementAnalyzer] Calling LLM ({router._client.__class__.__name__})...")
        result = router.generate_structured(
            "requirement_analysis",
            prompt=prompt,
            system=_SYSTEM_PROMPT)

        print(f"[RequirementAnalyzer] LLM Output Received in {result.latency_ms}ms | Model: {result.model} (is_mock={result.is_mock})")

        # Parse the LLM response — use it if valid, fallback if not
        analysis = self._parse_analysis(result, acs)

        pos_count = len(analysis.get("positive_scenarios", []))
        neg_count = len(analysis.get("negative_scenarios", []))
        bnd_count = len(analysis.get("boundary_scenarios", []))
        val_count = len(analysis.get("validation_scenarios", []))
        err_count = len(analysis.get("error_scenarios", []))
        total_scenarios = pos_count + neg_count + bnd_count + val_count + err_count
        print(f"[RequirementAnalyzer] Decomposed {total_scenarios} Test Scenarios (Pos: {pos_count}, Neg: {neg_count}, Bound: {bnd_count}, Valid: {val_count}, Err: {err_count}):")
        for cat_name, cat_key in [
            ("Positive", "positive_scenarios"),
            ("Negative", "negative_scenarios"),
            ("Boundary", "boundary_scenarios"),
            ("Validation", "validation_scenarios"),
            ("Security/Error", "error_scenarios")
        ]:
            scs = analysis.get(cat_key, [])
            if scs:
                print(f"   [{cat_name} ({len(scs)})]:")
                for s in scs:
                    sid = s.get("id", "SCN") if isinstance(s, dict) else "SCN"
                    desc = s.get("desc") or s.get("description") if isinstance(s, dict) else str(s)
                    print(f"     • [{sid}] {desc}")

        state["analysis"] = analysis
        state["current_stage"] = SERVICE_PLANNING
        self._record(workflow_id, "requirement_analysis", model_name=result.model,
                     latency_ms=result.latency_ms,
                     output_summary={"scenarios": total_scenarios, "is_mock": result.is_mock})
        return state

    def _parse_analysis(self, result, acs):
        """Parse Gemini's structured JSON response. Fallback to AC-derived scenarios."""
        parsed = None

        if not result.is_mock:
            try:
                parsed = json.loads(result.text)
            except (json.JSONDecodeError, TypeError):
                print(f"[RequirementAnalyzer] Could not parse LLM JSON, falling back to AC extraction.")
                parsed = None

        if parsed and isinstance(parsed, dict):
            # Ensure each scenario has an ID
            for key in ("positive_scenarios", "negative_scenarios", "boundary_scenarios",
                        "validation_scenarios", "error_scenarios"):
                scenarios = parsed.get(key, [])
                if isinstance(scenarios, list):
                    for sc in scenarios:
                        if isinstance(sc, dict) and "id" not in sc:
                            sc["id"] = self.nid("SCN")
                else:
                    parsed[key] = []

            return {
                "business_rules": parsed.get("business_rules", []),
                "positive_scenarios": parsed.get("positive_scenarios", []),
                "negative_scenarios": parsed.get("negative_scenarios", []),
                "boundary_scenarios": parsed.get("boundary_scenarios", []),
                "validation_scenarios": parsed.get("validation_scenarios", []),
                "error_scenarios": parsed.get("error_scenarios", []),
                "ambiguities": parsed.get("ambiguities", []),
                "traceability_ids": [self.nid("REQ") for _ in range(len(acs))],
                "model": result.model,
                "is_mock": result.is_mock,
            }

        # Fallback: derive scenarios from acceptance criteria directly
        return self._fallback_from_acs(acs, result)

    def _fallback_from_acs(self, acs, result):
        """Build scenarios from acceptance criteria when LLM output is unavailable."""
        positive, negative, boundary, validation, error = [], [], [], [], []

        for i, ac in enumerate(acs):
            ac_lower = ac.lower()
            scenario = {"id": self.nid("SCN"), "desc": ac, "ac_ref": f"AC-{i+1:02d}"}

            # Heuristic classification based on keywords
            if any(kw in ac_lower for kw in ("reject", "fail", "invalid", "error", "denied",
                                              "expired", "block", "refuse", "not allowed", "tampered", "missing", "unauthorized")):
                negative.append(scenario)
            elif any(kw in ac_lower for kw in ("limit", "maximum", "minimum", "boundary",
                                                "edge", "zero", "overflow", "exactly", "near")):
                boundary.append(scenario)
            elif any(kw in ac_lower for kw in ("validate", "format", "schema", "field", "type", "required", "check", "verify")):
                validation.append(scenario)
            elif any(kw in ac_lower for kw in ("exception", "crash", "timeout", "500", "unavailable")):
                error.append(scenario)
            else:
                positive.append(scenario)

        # Ensure at least one scenario exists
        if not positive and acs:
            positive.append({"id": self.nid("SCN"), "desc": f"Happy path for: {acs[0]}", "ac_ref": "AC-01"})

        return {
            "business_rules": [],
            "positive_scenarios": positive,
            "negative_scenarios": negative,
            "boundary_scenarios": boundary,
            "validation_scenarios": validation,
            "error_scenarios": error,
            "ambiguities": [],
            "traceability_ids": [self.nid("REQ") for _ in acs],
            "model": result.model,
            "is_mock": result.is_mock,
        }

    def _get_rag_context(self, state, query_text):
        """Retrieve relevant knowledge base context for the project."""
        try:
            project = state.get("project", {})
            project_id = project.get("id")
            if not project_id:
                return ""
            from app.rag.retrieval.retriever import get_retriever
            retriever = get_retriever()
            chunks = retriever.retrieve(project_id=project_id, query=query_text, top_k=5)
            if chunks:
                return "\n---\n".join(c.content[:500] for c in chunks[:5])
        except Exception as e:
            print(f"[RequirementAnalyzer] RAG retrieval failed: {e}")
        return ""
