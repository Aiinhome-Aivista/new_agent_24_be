import json
from app.llm.model_router.router import get_router
from app.audit.audit_log import record

PROMPT_TEMPLATE = """You are an API Review Agent.
You will be provided with a user story description, Acceptance Criteria, API Contracts, and potentially a Postman Collection.
Your job is to find out if there are any functions (endpoints/methods) or payloads defined in the story/collection that are MISSING from the planned API Contracts.

Story Description:
{story_description}

Acceptance Criteria:
{acceptance_criteria}

Planned API Contracts:
{api_contracts}

Postman Collection (if any):
{collection}

Please analyze the inputs carefully.
Output a JSON object with the following structure:
{{
    "missing_functions": [
        {{
            "method": "POST",
            "path": "/api/example",
            "reason": "Missing the create function mentioned in the story.",
            "expected_payload": "{{...}}"
        }}
    ],
    "review_notes": "Any other notes about payload mismatch or overall review."
}}
If nothing is missing and payloads look correct, return an empty list for missing_functions.
"""

class ReviewAgent:
    name = "ReviewAgent"

    def run(self, workflow_id: str, state: dict) -> dict:
        story = state.get("story") or {}
        acs = state.get("acceptance_criteria") or []
        contracts = state.get("api_contracts") or []
        collection_path = state.get("collection_path")
        
        collection_data = ""
        if collection_path:
            import os
            if os.path.exists(collection_path):
                try:
                    with open(collection_path, "r", encoding="utf-8") as f:
                        collection_data = f.read()
                except Exception as e:
                    collection_data = f"Error reading collection: {e}"

        prompt = PROMPT_TEMPLATE.format(
            story_description=story.get("description", ""),
            acceptance_criteria=json.dumps(acs, indent=2),
            api_contracts=json.dumps(contracts, indent=2),
            collection=collection_data
        )

        try:
            result = get_router().generate_structured(
                task_type="service_planning",
                prompt=prompt,
                system="You are a strict API reviewer."
            )
            if not isinstance(result, dict):
                result = {"missing_functions": [], "review_notes": "Invalid LLM response."}
        except Exception as e:
            result = {"missing_functions": [], "review_notes": f"LLM error: {e}"}

        record(
            event_type="agent_execution",
            workflow_id=workflow_id,
            metadata={
                "agent": "ReviewAgent",
                "status": "SUCCESS",
                "output_summary": result
            }
        )

        state["missing_functions"] = result.get("missing_functions", [])
        state["review_notes"] = result.get("review_notes", "")
        
        from app.workflows.state_machine import TEST_PLAN_REVIEW, TEST_GENERATION
        if state["missing_functions"]:
            state["current_stage"] = TEST_PLAN_REVIEW
        else:
            state["current_stage"] = TEST_GENERATION
            
        return state
