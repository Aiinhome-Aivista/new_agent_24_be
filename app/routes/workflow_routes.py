import uuid as _uuid
# pyrefly: ignore [missing-import]
from flask import Blueprint, request, g
from app.errors.handlers import ok, fail
from app.auth.decorators import require_auth, require_permission
from app.repositories.project_repo import get_story, get_project, story_acceptance_criteria
from app.repositories.workflow_repo import create_run, get_run, list_runs, list_agent_runs
from app.services.workflow_runner import dispatch_start
from app.workflows.state_machine import QUEUED, CREATED, REQUIREMENT_ANALYSIS
from app.audit.audit_log import record as audit
from app.extensions.db import query

workflow_bp = Blueprint("workflows", __name__)


@workflow_bp.route("/workflows", methods=["POST"])
@require_auth
@require_permission("workflow.create")
def start_workflow():
    body = request.get_json(silent=True) or {}
    story_uuid = body.get("story_uuid")
    capabilities = body.get("capabilities", [])
    story = get_story(story_uuid) if story_uuid else None
    if not story:
        return fail("VALIDATION_ERROR", "Valid story_uuid is required")

    # Prevent duplicate workflow creation for the same story
    existing_wf = query("SELECT workflow_id, status, current_stage FROM workflow_runs WHERE story_id=%s ORDER BY created_at DESC LIMIT 1", (story["id"],), fetchone=True)
    if existing_wf:
        return fail("CONFLICT", f"A workflow already exists for this story (Workflow ID: {existing_wf['workflow_id']})", 409, details={"existing_workflow_id": existing_wf["workflow_id"], "status": existing_wf["status"]})

    project = query("SELECT * FROM projects WHERE id=%s", (story["project_id"],), fetchone=True)
    acs = story_acceptance_criteria(story["id"])
    
    # If no criteria in DB table, extract from story description/title
    if not acs:
        desc = story.get("description", "") or ""
        extracted = []
        if desc:
            lines = [line.strip().lstrip("-*•1234567890. ") for line in desc.split("\n") if line.strip()]
            for l in lines:
                low = l.lower()
                # Skip story narrative template lines
                if (len(l) > 6 and not l.startswith("#") 
                        and not low.startswith("as a") 
                        and not low.startswith("i want") 
                        and not low.startswith("so that") 
                        and not low.startswith("in order") 
                        and not low.startswith("user story")
                        and not low.startswith("acceptance criteria")
                        and not low.startswith("description")):
                    extracted.append({"text": l})
        if not extracted:
            entity_name = "user" if "user" in story.get("title", "").lower() else "resource"
            extracted = [
                {"text": f"{entity_name.capitalize()} can be created through REST API via POST /api/{entity_name}s with valid parameters"},
                {"text": f"{entity_name.capitalize()} details can be retrieved by ID via GET /api/{entity_name}s/{{id}}"},
                {"text": f"{entity_name.capitalize()} details can be updated via PUT /api/{entity_name}s/{{id}}"},
                {"text": f"{entity_name.capitalize()} can be deleted via DELETE /api/{entity_name}s/{{id}}"},
                {"text": f"Invalid or duplicate request data is rejected with appropriate 4xx validation error"}
            ]
        acs = extracted

    contracts = query("""SELECT c.method, c.path, s.name AS service FROM api_contracts c
                         JOIN services s ON s.id=c.service_id WHERE s.project_id=%s""",
                      (story["project_id"],))

    # If no explicit contracts in DB, extract endpoints from ACs or derive clean REST endpoints
    if not contracts:
        story_text = f"{story.get('title', '')} {story.get('description', '')}".lower()
        ac_combined = " ".join(a.get("text", "") for a in acs)
        all_text = f"{story_text} {ac_combined.lower()}"

        # 1. Look for explicit endpoints in Acceptance Criteria (e.g. POST /api/auth/change-password)
        import re
        extracted_endpoints = re.findall(r'(GET|POST|PUT|DELETE|PATCH)\s+([/a-zA-Z0-9_\-\/{}\.]+)', ac_combined, re.IGNORECASE)
        if extracted_endpoints:
            contracts = []
            service_name = "AuthService" if any(k in all_text for k in ("auth", "password", "jwt", "login")) else "CoreService"
            for m, p in extracted_endpoints:
                clean_p = p.rstrip('`,.')
                if clean_p.startswith('/'):
                    contracts.append({
                        "service": service_name,
                        "method": m.upper(),
                        "path": clean_p
                    })

        if not contracts and not (project or {}).get("git_repo_url"):
            # Only generate fallback endpoint if no git repo is connected
            clean_name = "".join(c for c in story.get("title", "resource") if c.isalnum() or c in " -_").strip()
            endpoint_slug = clean_name.lower().replace(" ", "-") or "resources"
            if not endpoint_slug.endswith("s"):
                endpoint_slug += "s"
            service_name = (project or {}).get("name", "CoreService")
            # Determine main method from story title
            main_method = "POST" if any(k in story_text for k in ("create", "add", "register", "insert", "new")) else "GET"
            contracts = [
                {"service": service_name, "method": main_method, "path": f"/api/{endpoint_slug}"}
            ]

    workflow_id = str(_uuid.uuid4())
    state = {
        "current_stage": REQUIREMENT_ANALYSIS,
        "status": QUEUED,
        "project": project,
        "story": story,
        "acceptance_criteria": [a["text"] for a in acs],
        "api_contracts": contracts,
        "capabilities": capabilities,
    }

    # Clone / pull the git repo if configured
    git_repo_url = (project or {}).get("git_repo_url")
    if git_repo_url:
        try:
            from app.tools.repository.workspace import GitWorkspace
            ws = GitWorkspace(
                project_uuid=project["uuid"],
                repo_url=git_repo_url,
                branch=(project or {}).get("git_branch", "main")
            )
            clone_result = ws.clone_or_pull()
            state["workspace_path"] = str(ws.workspace_path)
            state["workspace_status"] = clone_result
            if ws.exists:
                state["project_structure"] = ws.find_project_structure()
            audit("git_clone", user_id=g.user_id, project_id=project["id"],
                  status="SUCCESS" if clone_result.get("success") else "FAILED",
                  metadata={"action": clone_result.get("action"), "error": clone_result.get("error")})
        except Exception as e:
            state["workspace_status"] = {"action": "error", "success": False, "error": str(e)}
            print(f"[Workflow] Git workspace setup failed: {e}")

    # Find Postman collection path if available
    collection_doc = query("""
        SELECT kd.id FROM knowledge_documents kd
        WHERE kd.project_id = %s AND kd.doc_type IN ('postman_collection', 'api_contract')
        ORDER BY kd.created_at DESC LIMIT 1
    """, (story["project_id"],), fetchone=True)
    if collection_doc:
        # Reconstruct collection from stored chunks
        import os, json as _json
        chunks = query("SELECT content FROM knowledge_chunks WHERE document_id=%s ORDER BY chunk_index",
                       (collection_doc["id"],))
        if chunks:
            collection_json = "".join([c["content"] for c in chunks])
            collection_dir = os.path.join(".", "tmp", "collections")
            os.makedirs(collection_dir, exist_ok=True)
            collection_file = os.path.join(collection_dir, f"{project['uuid']}.json")
            try:
                with open(collection_file, "w", encoding="utf-8") as f:
                    f.write(collection_json)
                state["collection_path"] = collection_file
            except Exception as e:
                print(f"[Workflow] Failed to export collection: {e}")

    create_run(workflow_id, story["project_id"], story["id"], "RUNNING", REQUIREMENT_ANALYSIS,
               capabilities, state, g.user_id)
    audit("workflow_creation", user_id=g.user_id, workflow_id=workflow_id,
          project_id=story["project_id"], story_id=story["id"], status="RUNNING")

    task_id, status = dispatch_start(workflow_id, state)
    return ok({"workflow_id": workflow_id, "task_id": task_id, "status": status}, "Workflow started", 201)



@workflow_bp.route("/workflows", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def workflows():
    project_uuid = request.args.get("project")
    return ok({"workflows": list_runs(project_uuid)})


@workflow_bp.route("/workflows/<workflow_id>", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def workflow_detail(workflow_id):
    run = get_run(workflow_id)
    if not run:
        return fail("NOT_FOUND", "Workflow not found", 404)
    return ok({"workflow": run, "agent_runs": list_agent_runs(workflow_id)})


@workflow_bp.route("/workflows/<workflow_id>/status", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def workflow_status(workflow_id):
    run = get_run(workflow_id)
    if not run:
        return fail("NOT_FOUND", "Workflow not found", 404)
    
    # Auto-healing: If workflow is in QUEUED/CREATED, automatically launch background execution
    if run.get("status") == "QUEUED" and run.get("current_stage") == "CREATED":
        state = run.get("state_json") or {}
        dispatch_start(workflow_id, state)
        run["status"] = "RUNNING"
        run["current_stage"] = "REQUIREMENT_ANALYSIS"

    return ok({
        "workflow_id": workflow_id,
        "status": run["status"],
        "current_stage": run["current_stage"],
        "current_agent": run["current_agent"],
        "project_uuid": run.get("project_uuid"),
        "story_title": run.get("story_title"),
    })


@workflow_bp.route("/workflows/<workflow_id>/sla", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def workflow_sla(workflow_id):
    from app.services.sla_service import evaluate_workflow_sla
    sla_data = evaluate_workflow_sla(workflow_id)
    if not sla_data:
        return fail("NOT_FOUND", "Workflow not found", 404)
    return ok({"sla": sla_data})


@workflow_bp.route("/agent-runs", methods=["GET"])
@require_auth
@require_permission("workflow.read")
def agent_runs():
    return ok({"agent_runs": list_agent_runs()})
