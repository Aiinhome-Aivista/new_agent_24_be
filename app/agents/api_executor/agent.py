"""
ApiExecutorAgent — Stage 8 (API_EXECUTION).
Executes real API tests against the target host using Postman/Bruno collection templates.

Architectural Principles (prompt.md):
- Real API execution is mandatory — never simulate or fabricate responses.
- Adapts existing Postman collection requests for AC-specific scenarios (mutating payloads per AC).
- Captures real request, response, status, assertions, timestamp, and latency.
- Clearly separates implementation failures from infrastructure failures (host offline -> INCONCLUSIVE).
- Updates AC -> API -> Code mapping with actual execution evidence.
"""
import os
import json
import uuid
from app.agents.base import BaseAgent
from app.tools.api_runner.runner import get_runner
from app.repositories.test_repo import save_execution_run_with_results
from app.workflows.state_machine import CODE_VALIDATION


class ApiExecutorAgent(BaseAgent):
    """Authoritative API execution stage. The LLM never invents execution results."""
    name = "api_executor"

    def run(self, workflow_id, state):
        target_host = state.get("target_host") or state.get("base_url") or "http://127.0.0.1:5001"
        collection_data = self._resolve_postman_collection(state)
        story = state.get("story", {})
        story_uuid = story.get("uuid") or story.get("id")
        project_uuid = (state.get("project") or {}).get("uuid") or (state.get("project") or {}).get("id")

        executed_autonomous = False
        if collection_data and collection_data.get("item"):
            try:
                # ── Real Autonomous API Execution via Postman Collection Templates ─
                print(f"\n[ApiExecutor] Executing Real API verification against: {target_host} using Postman collection...")
                from app.agents.api_executor.autonomous_agent import AutonomousApiVerifierAgent
                verifier = AutonomousApiVerifierAgent(timeout=15)

                auto_evidence = verifier.execute_autonomous_verification(
                    base_url=target_host,
                    collection_data=collection_data,
                    story_uuid=story_uuid,
                    project_uuid=project_uuid,
                    collection_name=collection_data.get("info", {}).get("name", "API Test Suite"),
                    is_mock=False,
                )

                results = auto_evidence.get("results", [])
                passed = sum(1 for r in results if r.get("passed"))
                failed = len(results) - passed
                is_mock = auto_evidence.get("is_mock", False)

                run_id = save_execution_run_with_results(
                    str(uuid.uuid4()), workflow_id,
                    runner="autonomous_verifier" if not is_mock else "mock",
                    environment="live" if not is_mock else "simulated",
                    collection=collection_data.get("info", {}).get("name", "Postman Collection"),
                    status="COMPLETED",
                    total=len(results),
                    passed=passed,
                    failed=failed,
                    is_mock=1 if is_mock else 0,
                    results=results,
                )

                state["execution"] = {
                    "run_id": run_id,
                    "total": len(results),
                    "passed": passed,
                    "failed": failed,
                    "is_mock": is_mock,
                    "target_host": target_host,
                }
                state["autonomous_evidence"] = auto_evidence
                state["api_execution_results"] = results
                state["postman_collection"] = collection_data

                # ── Update AC -> API -> Code Traceability Matrix ─────────────────
                self._update_traceability_results(state, results, auto_evidence)

                print(f"[ApiExecutor] Real API execution complete: {passed}/{len(results)} passed, {failed} failed (is_mock={is_mock}).")
                executed_autonomous = True
            except Exception as e:
                print(f"[ApiExecutor] Autonomous execution failed ({e}) — falling back to baseline runner.")

        if not executed_autonomous:
            # ── Fallback to runner if no collection is provided or items missing ─
            print("[ApiExecutor] Using baseline runner.")
            runner = get_runner()
            collection_path = state.get("collection_path")
            environment = state.get("environment", "default")
            test_cases = state.get("generated_tests", [])

            run = runner.run(collection_path, environment, test_cases=test_cases)
            passed = sum(1 for r in run.results if r.get("passed"))
            failed = len(run.results) - passed

            run_id = save_execution_run_with_results(
                str(uuid.uuid4()), workflow_id,
                runner="mock" if run.is_mock else "newman",
                environment=environment, collection=collection_path or "n/a",
                status="COMPLETED", total=len(run.results), passed=passed, failed=failed,
                is_mock=1 if run.is_mock else 0,
                results=run.results,
            )

            state["execution"] = {
                "run_id": run_id,
                "total": len(run.results),
                "passed": passed,
                "failed": failed,
                "is_mock": run.is_mock,
            }
            state["api_execution_results"] = run.results

        state["current_stage"] = CODE_VALIDATION
        self._record(
            workflow_id,
            "api_execution",
            tool_name="autonomous_verifier" if collection_data else "api_runner",
            output_summary={
                "total": state["execution"].get("total", 0),
                "passed": state["execution"].get("passed", 0),
                "failed": state["execution"].get("failed", 0),
            }
        )
        return state

    def _resolve_postman_collection(self, state: dict) -> dict | None:
        """Dynamically locates Postman collection from state, workspace, or database."""
        # 1. Directly in state
        if state.get("postman_collection"):
            return state["postman_collection"]

        # 2. Path in state
        coll_path = state.get("collection_path")
        if coll_path and os.path.isfile(coll_path):
            try:
                with open(coll_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        # 3. Scan workspace_path directory
        ws_path = state.get("workspace_path")
        if ws_path and os.path.isdir(ws_path):
            for fname in os.listdir(ws_path):
                if fname.endswith(".json") and ("postman" in fname.lower() or "collection" in fname.lower()):
                    try:
                        with open(os.path.join(ws_path, fname), "r", encoding="utf-8") as f:
                            return json.load(f)
                    except Exception:
                        pass

        # 4. Check project knowledge base documents in DB
        proj_id = (state.get("project") or {}).get("id") or (state.get("story") or {}).get("project_id")
        if proj_id:
            try:
                from app.extensions.db import query as db_query
                kdoc = db_query("""
                    SELECT kd.id, kd.source FROM knowledge_documents kd
                    WHERE kd.project_id = %s AND (kd.doc_type IN ('postman_collection', 'api_contract', 'postman', 'openapi') OR kd.title LIKE '%.json')
                    ORDER BY kd.created_at DESC LIMIT 1
                """, (proj_id,), fetchone=True)
                if kdoc:
                    if kdoc.get("source") and os.path.isfile(kdoc["source"]):
                        with open(kdoc["source"], "r", encoding="utf-8") as pf:
                            return json.load(pf)
                    else:
                        kchunks = db_query("SELECT content FROM knowledge_chunks WHERE document_id=%s ORDER BY chunk_index", (kdoc["id"],))
                        if kchunks:
                            return json.loads("".join([c["content"] for c in kchunks]))
            except Exception as db_err:
                print(f"[ApiExecutor] Knowledge base query note: {db_err}")

        # 5. Check repo root for collections (e.g. ticket-management.postman_collection.json)
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
        if os.path.isdir(root_dir):
            for fname in os.listdir(root_dir):
                if fname.endswith(".json") and ("postman" in fname.lower() or "collection" in fname.lower()):
                    try:
                        with open(os.path.join(root_dir, fname), "r", encoding="utf-8") as f:
                            return json.load(f)
                    except Exception:
                        pass

        return None

    def _update_traceability_results(self, state: dict, results: list, auto_evidence: dict):
        """Updates ac_api_code_mapping records with real execution evidence and final assessments."""
        mapping = state.get("ac_api_code_mapping") or []
        if not mapping:
            return

        is_unreachable = auto_evidence.get("summary_recommendation") == "API execution blocked (host unreachable)"

        for record in mapping:
            ac_key = record.get("ac_key", "")
            # Find matching execution result
            matching_res = []
            for r in results:
                t_key = r.get("test_key", "") or r.get("name", "")
                if ac_key in t_key or any(ac_key == a for a in r.get("ac_keys", [])):
                    matching_res.append(r)

            if is_unreachable:
                record["api_execution_result"] = "INCONCLUSIVE"
                record["final_assessment"] = "INCONCLUSIVE / EXECUTION BLOCKED"
                record["assessment_reason"] = "Target API host was offline or unreachable during execution."
            elif matching_res:
                all_passed = all(r.get("passed") for r in matching_res)
                if all_passed:
                    record["api_execution_result"] = "PASS"
                    if record.get("implementation_status") == "SUPPORTED":
                        record["final_assessment"] = "SATISFIED"
                    else:
                        record["final_assessment"] = "PARTIALLY SATISFIED"
                else:
                    record["api_execution_result"] = "FAIL"
                    record["final_assessment"] = "NOT SATISFIED / IMPLEMENTATION GAP"
                    deviations = [d.get("explanation") for r in matching_res for d in r.get("deviations", []) if d.get("explanation")]
                    record["assessment_reason"] = "; ".join(deviations[:2]) if deviations else "API scenario assertion failed against actual response."
            else:
                if record.get("implementation_status") == "NOT_IMPLEMENTED":
                    record["api_execution_result"] = "NOT_EXECUTABLE"
                    record["final_assessment"] = "NOT SATISFIED / IMPLEMENTATION GAP"
                    record["assessment_reason"] = "Endpoint not implemented in codebase."
                else:
                    record["api_execution_result"] = "NOT_TESTED"
                    record["final_assessment"] = "INCONCLUSIVE"

        state["ac_api_code_mapping"] = mapping
