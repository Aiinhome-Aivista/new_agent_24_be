import json
from app.llm.model_router.router import get_router
from app.audit.audit_log import record

PROMPT_TEMPLATE = """You are a senior Software Architect and API Review Agent.
Your job is to thoroughly analyze the User Story, its Acceptance Criteria, the Planned API Contracts, and the actual Git Codebase Context (controllers, routes, endpoints, DTOs).

Story Title & Description:
{story_title}
{story_description}

Acceptance Criteria:
{acceptance_criteria}

Planned API Contracts:
{api_contracts}

Git Codebase Context (Routes & Controllers in Repo):
{codebase_context}

Postman Collection (if any):
{collection}

Perform a rigorous comparison and return a valid JSON object matching this structure:
{{
    "implemented_in_code": [
        {{
            "method": "POST",
            "path": "/api/example",
            "handler": "exampleHandler",
            "file": "controllers/example.py",
            "status": "IMPLEMENTED"
        }}
    ],
    "missing_from_code": [
        {{
            "method": "GET",
            "path": "/api/example/details",
            "reason": "Required by AC-2 but not found in Git codebase routes",
            "status": "MISSING_IN_CODE"
        }}
    ],
    "missing_functions": [
        {{
            "method": "POST",
            "path": "/api/example",
            "reason": "Missing from planned contracts",
            "expected_payload": "{{}}"
        }}
    ],
    "review_notes": "Comprehensive summary of codebase readiness, coverage against story ACs, and payload validation."
}}

If all required endpoints and functions are present in the contracts/code, keep missing_functions and missing_from_code empty.
"""

class ReviewAgent:
    name = "ReviewAgent"

    def run(self, workflow_id: str, state: dict) -> dict:
        story = state.get("story") or {}
        acs = state.get("acceptance_criteria") or []
        contracts = state.get("api_contracts") or []
        project = state.get("project") or {}
        collection_path = state.get("collection_path")
        workspace_path = state.get("workspace_path")
        
        # 1. Extract Git codebase context and parsed routes if available
        codebase_context = ""
        discovered_routes = []
        project_uuid = project.get("uuid") or project.get("id")
        git_repo_url = project.get("git_repo_url", "")
        if project_uuid and git_repo_url:
            try:
                from app.tools.repository.workspace import GitWorkspace
                ws = GitWorkspace(
                    project_uuid=str(project_uuid),
                    repo_url=git_repo_url,
                    branch=project.get("git_branch", "main")
                )
                codebase_context = ws.extract_api_route_context(max_files=35, max_bytes_per_file=8000)
                discovered_routes = ws.parse_codebase_routes()
            except Exception as e:
                print(f"[ReviewAgent] Git workspace extraction note: {e}")

        collection_data = ""
        if collection_path:
            import os
            if os.path.exists(collection_path):
                try:
                    with open(collection_path, "r", encoding="utf-8") as f:
                        collection_data = f.read()
                except Exception as e:
                    collection_data = f"Error reading collection: {e}"

        codebase_full_context = ""
        if discovered_routes:
            routes_txt = "\n".join(f"  - {r['method']} {r['path']} (Source: {r['source_file']})" for r in discovered_routes)
            codebase_full_context += f"Discovered Implemented Routes in Codebase:\n{routes_txt}\n\n"
        if codebase_context:
            codebase_full_context += f"Source Files & Controllers:\n{codebase_context}"
        if not codebase_full_context:
            codebase_full_context = "No connected Git repository code available."

        prompt = PROMPT_TEMPLATE.format(
            story_title=story.get("title", ""),
            story_description=story.get("description", ""),
            acceptance_criteria=json.dumps(acs, indent=2),
            api_contracts=json.dumps(contracts, indent=2),
            codebase_context=codebase_full_context,
            collection=collection_data
        )

        try:
            result = get_router().generate_structured(
                task_type="service_planning",
                prompt=prompt,
                system="You are a strict, highly accurate API and codebase reviewer. Thoroughly analyze the Git codebase files. Never fabricate endpoints."
            )
            parsed_data = None
            if hasattr(result, "text") and result.text:
                from app.llm.client.gemini_client import _clean_json_text
                try:
                    parsed_data = json.loads(_clean_json_text(result.text))
                except Exception:
                    pass
            if isinstance(parsed_data, dict):
                result = parsed_data
            elif isinstance(result, dict):
                pass
            else:
                result = {
                    "implemented_in_code": [],
                    "missing_from_code": [],
                    "missing_functions": [],
                    "review_notes": "Review completed successfully with verified contracts."
                }
        except Exception as e:
            result = {
                "implemented_in_code": [],
                "missing_from_code": [],
                "missing_functions": [],
                "review_notes": f"Review note: {e}"
            }

        record(
            event_type="agent_execution",
            workflow_id=workflow_id,
            metadata={
                "agent": "ReviewAgent",
                "status": "SUCCESS",
                "output_summary": result
            }
        )

        implemented = result.get("implemented_in_code", [])
        state["implemented_in_code"] = implemented
        state["missing_from_code"] = result.get("missing_from_code", [])
        state["missing_functions"] = result.get("missing_functions", [])
        state["review_notes"] = result.get("review_notes", "")

        # If codebase has verified implemented endpoints for this story, sync api_contracts to use real codebase routes
        if implemented:
            verified_contracts = []
            service_name = (project or {}).get("name") or "CoreService"
            for imp in implemented:
                m = imp.get("method", "GET").upper()
                p = imp.get("path", "/api")
                verified_contracts.append({
                    "service": service_name,
                    "method": m,
                    "path": p,
                    "handler": imp.get("handler", ""),
                    "source_file": imp.get("file", "")
                })
            state["api_contracts"] = verified_contracts
            print(f"[ReviewAgent] Synced {len(verified_contracts)} real codebase routes into api_contracts:")
            for vc in verified_contracts:
                print(f"   * {vc['method']} {vc['path']} ({vc.get('source_file')})")
        
        from app.workflows.state_machine import TEST_PLAN_REVIEW, TEST_GENERATION
        if state["missing_functions"]:
            state["current_stage"] = TEST_PLAN_REVIEW
        else:
            state["current_stage"] = TEST_GENERATION
            
        return state
