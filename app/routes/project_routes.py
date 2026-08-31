"""Project, Story, Knowledge Base, and API Contract routes."""
import uuid as _uuid
import json
# pyrefly: ignore [missing-import]
from flask import Blueprint, request, g
from app.errors.handlers import ok, fail
from app.auth.decorators import require_auth, require_permission
from app.repositories.project_repo import (
    list_projects, get_project, create_project, delete_project,
    list_stories, get_story, create_story, delete_story,
    story_acceptance_criteria, create_acceptance_criterion,
    list_knowledge_documents, list_services_and_contracts,
    create_service, create_api_contract
)
from app.rag.ingestion.indexer import ingest_document, delete_document
from app.rag.retrieval.retriever import get_retriever
from app.audit.audit_log import record as audit
from app.extensions.db import query
from app.tools.repository import validate_git_connection

project_bp = Blueprint("projects", __name__)


# -----------------------------------------------------------------------------
# PROJECTS
# -----------------------------------------------------------------------------

@project_bp.route("/projects", methods=["GET"])
@require_auth
@require_permission("project.read")
def get_projects():
    return ok({"projects": list_projects()})


@project_bp.route("/projects/<uuid>", methods=["GET"])
@require_auth
@require_permission("project.read")
def project_detail(uuid):
    p = get_project(uuid)
    if not p:
        return fail("NOT_FOUND", "Project not found", 404)
    workflows = query("""
        SELECT w.workflow_id, w.status, w.current_stage, w.current_agent, w.created_at,
               s.title AS story_title, s.external_key AS story_key
        FROM workflow_runs w
        JOIN stories s ON s.id=w.story_id
        WHERE w.project_id=%s
        ORDER BY w.created_at DESC
    """, (p["id"],))
    return ok({
        "project": p,
        "stories": list_stories(uuid),
        "knowledge": list_knowledge_documents(p["id"]),
        "contracts": list_services_and_contracts(p["id"]),
        "workflows": workflows or []
    })


@project_bp.route("/projects/<uuid>", methods=["DELETE"])
@require_auth
@require_permission("project.write")
def remove_project(uuid):
    p = get_project(uuid)
    if not p:
        return fail("NOT_FOUND", "Project not found", 404)
    audit("project_deletion", user_id=getattr(g, "user_id", None), project_id=p["id"], status="SUCCESS", metadata={"project_uuid": uuid, "project_name": p.get("name")})
    success = delete_project(uuid)
    if success:
        return ok({"message": f"Project '{p.get('name')}' deleted successfully", "uuid": uuid})
    return fail("DELETE_FAILED", "Failed to delete project", 500)


@project_bp.route("/projects", methods=["POST"])
@require_auth
@require_permission("project.write")
def add_project():
    body = request.get_json(silent=True) or {}
    key_code = body.get("key_code", "").strip()
    name = body.get("name", "").strip()
    description = body.get("description", "").strip()
    target_language = body.get("target_language", "java").strip()
    target_framework = body.get("target_framework", "junit5").strip()
    coding_standard = body.get("coding_standard", "checkstyle-google").strip()

    git_repo_url = body.get("git_repo_url", "").strip() or None
    git_provider = body.get("git_provider", "github").strip()
    git_branch = body.get("git_branch", "main").strip()
    base_branch = body.get("base_branch", "main").strip()
    tech_stack = body.get("tech_stack", "").strip() or None
    build_tool = body.get("build_tool", "").strip() or None
    app_type = body.get("app_type", "REST API / Microservice").strip()
    deployment_target = body.get("deployment_target", "").strip() or None
    testing_framework = body.get("testing_framework", target_framework).strip()
    integration_test_framework = body.get("integration_test_framework", "").strip() or None
    mocking_library = body.get("mocking_library", "").strip() or None
    target_coverage = body.get("target_coverage", "80%").strip()
    frontend_framework = body.get("frontend_framework", "").strip() or None
    backend_framework = body.get("backend_framework", "").strip() or None

    if not key_code or not name:
        return fail("VALIDATION_ERROR", "Project key_code and name are required")

    existing = query("SELECT id FROM projects WHERE key_code=%s", (key_code.upper(),), fetchone=True)
    if existing:
        return fail("CONFLICT", f"Project with key '{key_code.upper()}' already exists", 409)

    project_uuid = str(_uuid.uuid4())
    project_id = create_project(
        project_uuid, key_code, name, description,
        target_language, target_framework, coding_standard, g.user_id,
        git_repo_url=git_repo_url,
        git_provider=git_provider,
        git_branch=git_branch,
        base_branch=base_branch,
        tech_stack=tech_stack,
        build_tool=build_tool,
        app_type=app_type,
        deployment_target=deployment_target,
        testing_framework=testing_framework,
        integration_test_framework=integration_test_framework,
        mocking_library=mocking_library,
        target_coverage=target_coverage,
        frontend_framework=frontend_framework,
        backend_framework=backend_framework
    )

    # Link creator as ARCHITECT / ADMIN
    query("""
        INSERT INTO project_members (project_id, user_id, role_code)
        VALUES (%s, %s, 'ARCHITECT')
    """, (project_id, g.user_id))

    audit("project_creation", user_id=g.user_id, project_id=project_id, status="SUCCESS",
          metadata={"key_code": key_code, "name": name, "git_branch": git_branch, "tech_stack": tech_stack, "app_type": app_type})

    return ok({"project_id": project_id, "uuid": project_uuid, "key_code": key_code, "name": name},
              "Project created successfully", 201)


@project_bp.route("/projects/test-git-connection", methods=["POST"])
@require_auth
def test_git_connection_adhoc():
    """Test connectivity to any Git repository / branch before or after creating a project."""
    body = request.get_json(silent=True) or {}
    git_repo_url = body.get("git_repo_url", "").strip()
    git_branch = body.get("git_branch", "main").strip() or "main"
    git_provider = body.get("git_provider", "github").strip() or "github"
    token = body.get("token", "").strip() or None

    result = validate_git_connection(git_repo_url, git_branch=git_branch, git_provider=git_provider, token=token)
    audit("git_connection_test", user_id=g.user_id, status="SUCCESS" if result.get("connected") else "FAILED",
          metadata={"git_repo_url": git_repo_url, "git_branch": git_branch, "result_status": result.get("status")})
    return ok(result)


@project_bp.route("/projects/<uuid>/test-git-connection", methods=["POST"])
@require_auth
@require_permission("project.read")
def test_project_git_connection(uuid):
    """Test Git connectivity for an existing project workspace."""
    p = get_project(uuid)
    if not p:
        return fail("NOT_FOUND", "Project not found", 404)

    body = request.get_json(silent=True) or {}
    git_repo_url = body.get("git_repo_url") or p.get("git_repo_url")
    git_branch = body.get("git_branch") or p.get("git_branch") or "main"
    git_provider = body.get("git_provider") or p.get("git_provider") or "github"
    token = body.get("token", "").strip() or None

    result = validate_git_connection(git_repo_url, git_branch=git_branch, git_provider=git_provider, token=token)
    audit("git_connection_test", user_id=g.user_id, project_id=p["id"], status="SUCCESS" if result.get("connected") else "FAILED",
          metadata={"git_repo_url": git_repo_url, "git_branch": git_branch, "result_status": result.get("status")})
    return ok(result)


# -----------------------------------------------------------------------------
# USER STORIES & ACCEPTANCE CRITERIA
# -----------------------------------------------------------------------------

@project_bp.route("/stories", methods=["GET"])
@require_auth
@require_permission("story.read")
def get_stories():
    project_uuid = request.args.get("project")
    return ok({"stories": list_stories(project_uuid)})


@project_bp.route("/stories/<uuid>", methods=["GET"])
@require_auth
@require_permission("story.read")
def story_detail(uuid):
    s = get_story(uuid)
    if not s:
        return fail("NOT_FOUND", "Story not found", 404)
    acs = story_acceptance_criteria(s["id"]) if s else []
    return ok({"story": s, "acceptance_criteria": acs})


@project_bp.route("/stories/<uuid>", methods=["DELETE"])
@require_auth
@require_permission("story.write")
def remove_story(uuid):
    s = get_story(uuid)
    if not s:
        return fail("NOT_FOUND", "Story not found", 404)
    user_id = getattr(g, "user_id", None)
    audit("story_deletion", user_id=user_id, project_id=s["project_id"], story_id=s["id"],
          status="SUCCESS", metadata={"story_uuid": uuid, "external_key": s.get("external_key"), "title": s.get("title")})
    success = delete_story(uuid)
    if success:
        return ok({"message": f"Story '{s.get('external_key')}' and all associated data deleted successfully", "uuid": uuid})
    return fail("DELETE_FAILED", "Failed to delete story", 500)


@project_bp.route("/stories", methods=["POST"])
@require_auth
@require_permission("story.write")
def add_story():
    body = request.get_json(silent=True) or {}
    project_uuid = body.get("project_uuid")
    external_key = body.get("external_key", "").strip()
    title = body.get("title", "").strip()
    description = body.get("description", "").strip()
    sprint = body.get("sprint", "Sprint 1").strip()
    acceptance_criteria = body.get("acceptance_criteria", [])

    if not project_uuid or not title:
        return fail("VALIDATION_ERROR", "project_uuid and title are required")

    project = get_project(project_uuid)
    if not project:
        return fail("NOT_FOUND", "Project not found", 404)

    if not external_key:
        count = query("SELECT COUNT(*) AS c FROM stories WHERE project_id=%s", (project["id"],), fetchone=True)["c"]
        external_key = f"{project['key_code']}-{count + 101}"

    story_uuid = str(_uuid.uuid4())
    story_id = create_story(story_uuid, project["id"], external_key, title, description, sprint, g.user_id)

    # Insert acceptance criteria if provided
    inserted_acs = []
    for idx, ac in enumerate(acceptance_criteria, start=1):
        ac_key = ac.get("ac_key") if isinstance(ac, dict) else f"AC-{idx}"
        ac_text = ac.get("text") if isinstance(ac, dict) else str(ac)
        if ac_text.strip():
            ac_uuid = str(_uuid.uuid4())
            create_acceptance_criterion(ac_uuid, story_id, ac_key, ac_text.strip())
            inserted_acs.append({"ac_key": ac_key, "text": ac_text.strip()})

    audit("story_creation", user_id=g.user_id, project_id=project["id"], story_id=story_id,
          status="SUCCESS", metadata={"external_key": external_key, "acs_count": len(inserted_acs)})

    return ok({
        "story_id": story_id,
        "uuid": story_uuid,
        "external_key": external_key,
        "title": title,
        "acceptance_criteria": inserted_acs
    }, "Story created successfully", 201)


@project_bp.route("/stories/<uuid>/acceptance-criteria", methods=["POST"])
@require_auth
@require_permission("story.write")
def add_acceptance_criterion(uuid):
    story = get_story(uuid)
    if not story:
        return fail("NOT_FOUND", "Story not found", 404)

    body = request.get_json(silent=True) or {}
    text = body.get("text", "").strip()
    if not text:
        return fail("VALIDATION_ERROR", "Acceptance criterion text is required")

    existing_count = len(story_acceptance_criteria(story["id"]))
    ac_key = body.get("ac_key", f"AC-{existing_count + 1}").strip()
    ac_uuid = str(_uuid.uuid4())

    create_acceptance_criterion(ac_uuid, story["id"], ac_key, text)
    return ok({"uuid": ac_uuid, "ac_key": ac_key, "text": text}, "Acceptance criterion added", 201)


# -----------------------------------------------------------------------------
# KNOWLEDGE BASE & DOCUMENT INGESTION
# -----------------------------------------------------------------------------

@project_bp.route("/projects/<project_uuid>/knowledge", methods=["GET"])
@require_auth
@require_permission("project.read")
def get_project_knowledge(project_uuid):
    project = get_project(project_uuid)
    if not project:
        return fail("NOT_FOUND", "Project not found", 404)
    docs = list_knowledge_documents(project["id"])
    return ok({"documents": docs, "project": project})


@project_bp.route("/projects/<project_uuid>/knowledge", methods=["POST"])
@require_auth
@require_permission("knowledge.write")
def upload_knowledge(project_uuid):
    project = get_project(project_uuid)
    if not project:
        return fail("NOT_FOUND", "Project not found", 404)

    doc_type = request.form.get("doc_type", "general").strip()
    version = request.form.get("version", "v1").strip()

    # Case A: File upload (multipart)
    if "file" in request.files:
        file = request.files["file"]
        if not file.filename:
            return fail("VALIDATION_ERROR", "No file selected")
        content_bytes = file.read()
        file_name = file.filename
    # Case B: Raw text payload
    else:
        body = request.get_json(silent=True) or {}
        text_content = body.get("content", "").strip()
        file_name = body.get("title", f"{doc_type}_{_uuid.uuid4().hex[:6]}.txt").strip()
        doc_type = body.get("doc_type", doc_type)
        version = body.get("version", version)
        if not text_content:
            return fail("VALIDATION_ERROR", "File or text content is required")
        content_bytes = text_content.encode("utf-8")

    result = ingest_document(
        project_id=project["id"],
        file_name=file_name,
        content_bytes=content_bytes,
        doc_type=doc_type,
        version=version,
        uploaded_by=g.user_id
    )

    audit("knowledge_upload", user_id=g.user_id, project_id=project["id"],
          status="SUCCESS", metadata={"doc_uuid": result["uuid"], "doc_type": doc_type, "file_name": file_name})

    return ok(result, "Document ingested and indexed successfully", 201)


@project_bp.route("/knowledge/<doc_uuid>", methods=["DELETE"])
@require_auth
@require_permission("knowledge.write")
def delete_knowledge(doc_uuid):
    success = delete_document(doc_uuid)
    if not success:
        return fail("NOT_FOUND", "Document not found", 404)
    audit("knowledge_deletion", user_id=g.user_id, status="SUCCESS", metadata={"doc_uuid": doc_uuid})
    return ok({}, "Document deleted")


@project_bp.route("/projects/<project_uuid>/rag/query", methods=["POST"])
@require_auth
@require_permission("project.read")
def query_rag(project_uuid):
    project = get_project(project_uuid)
    if not project:
        return fail("NOT_FOUND", "Project not found", 404)

    body = request.get_json(silent=True) or {}
    query_text = body.get("query", "").strip()
    top_k = int(body.get("top_k", 5))
    if not query_text:
        return fail("VALIDATION_ERROR", "query string is required")

    retriever = get_retriever()
    chunks = retriever.retrieve(project_id=project["id"], query=query_text, top_k=top_k)

    return ok({
        "project_id": project["id"],
        "project_key": project["key_code"],
        "query": query_text,
        "chunks": [{"content": c.content, "source": c.source, "metadata": c.metadata} for c in chunks]
    })


# -----------------------------------------------------------------------------
# API CONTRACTS & SERVICES
# -----------------------------------------------------------------------------

@project_bp.route("/projects/<project_uuid>/contracts", methods=["GET"])
@require_auth
@require_permission("project.read")
def get_contracts(project_uuid):
    project = get_project(project_uuid)
    if not project:
        return fail("NOT_FOUND", "Project not found", 404)
    return ok(list_services_and_contracts(project["id"]))


@project_bp.route("/projects/<project_uuid>/contracts", methods=["POST"])
@require_auth
@require_permission("project.write")
def add_contract(project_uuid):
    project = get_project(project_uuid)
    if not project:
        return fail("NOT_FOUND", "Project not found", 404)

    body = request.get_json(silent=True) or {}
    service_name = body.get("service_name", "").strip()
    method = body.get("method", "POST").upper().strip()
    path = body.get("path", "").strip()
    request_schema = body.get("request_schema", {})
    response_schema = body.get("response_schema", {})

    if not service_name or not path:
        return fail("VALIDATION_ERROR", "service_name and path are required")

    # Find or create service
    service = query("SELECT * FROM services WHERE project_id=%s AND name=%s", (project["id"], service_name), fetchone=True)
    if not service:
        service_uuid = str(_uuid.uuid4())
        service_id = create_service(service_uuid, project["id"], service_name, f"Service {service_name}")
    else:
        service_id = service["id"]

    contract_uuid = str(_uuid.uuid4())
    create_api_contract(contract_uuid, service_id, method, path, request_schema, response_schema)

    return ok({"uuid": contract_uuid, "service": service_name, "method": method, "path": path},
              "API contract added successfully", 201)


@project_bp.route("/projects/<project_uuid>/contracts/upload-collection", methods=["POST"])
@require_auth
@require_permission("project.write")
def upload_collection(project_uuid):
    project = get_project(project_uuid)
    if not project:
        return fail("NOT_FOUND", "Project not found", 404)

    if "file" not in request.files:
        return fail("VALIDATION_ERROR", "Postman (.json) or Bruno (.bru / .json) file required")

    file = request.files["file"]
    filename = file.filename or "collection"
    raw_bytes = file.read()
    raw_text = raw_bytes.decode("utf-8", errors="replace")

    contracts_created = 0
    service_name = "ImportedService"
    data = None

    # Check if JSON (Postman or Bruno JSON export)
    try:
        data = json.loads(raw_text)
    except Exception:
        data = None

    if data and isinstance(data, dict):
        # Postman / Standard Collection JSON
        doc_type = "postman_collection" if ("_postman_id" in data.get("info", {}) or "schema" in data.get("info", {}) or "item" in data) else "api_contract"
        service_name = data.get("info", {}).get("name", filename.replace(".json", ""))

        ingest_document(
            project_id=project["id"],
            file_name=filename,
            content_bytes=raw_bytes,
            doc_type=doc_type,
            uploaded_by=g.user_id
        )

        service = query("SELECT * FROM services WHERE project_id=%s AND name=%s", (project["id"], service_name), fetchone=True)
        service_id = service["id"] if service else create_service(str(_uuid.uuid4()), project["id"], service_name, "Imported from collection")

        def extract_requests(items):
            nonlocal contracts_created
            for it in items:
                if "item" in it:
                    extract_requests(it["item"])
                elif "request" in it:
                    req = it["request"]
                    method = req.get("method", "GET").upper()
                    url = req.get("url", {})
                    raw_path = url.get("raw") if isinstance(url, dict) else str(url)
                    body = req.get("body", {})
                    req_schema = {}
                    if body.get("raw"):
                        try:
                            req_schema = json.loads(body["raw"])
                        except Exception:
                            req_schema = {"raw": body["raw"]}
                    create_api_contract(str(_uuid.uuid4()), service_id, method, raw_path, req_schema, {})
                    contracts_created += 1

        if "item" in data:
            extract_requests(data["item"])

    else:
        # Bruno (.bru) Text File Parser
        import re
        service_name = filename.replace(".bru", "").replace("_", " ").title()
        
        ingest_document(
            project_id=project["id"],
            file_name=filename,
            content_bytes=raw_bytes,
            doc_type="bruno_collection",
            uploaded_by=g.user_id
        )

        service = query("SELECT * FROM services WHERE project_id=%s AND name=%s", (project["id"], service_name), fetchone=True)
        service_id = service["id"] if service else create_service(str(_uuid.uuid4()), project["id"], service_name, "Imported from Bruno collection")

        # Regex match HTTP method block: get { url: ... }, post { url: ... }
        method_match = re.search(r"(get|post|put|delete|patch|options|head)\s*\{([^}]+)\}", raw_text, re.IGNORECASE)
        if method_match:
            method = method_match.group(1).upper()
            block_content = method_match.group(2)
            url_match = re.search(r"url:\s*(\S+)", block_content)
            raw_path = url_match.group(1) if url_match else "/api/resource"

            req_schema = {}
            body_match = re.search(r"body:json\s*\{([\s\S]+?)\}\s*(?:$|\n\w)", raw_text)
            if body_match:
                try:
                    req_schema = json.loads(body_match.group(1).strip())
                except Exception:
                    req_schema = {"raw": body_match.group(1).strip()}

            create_api_contract(str(_uuid.uuid4()), service_id, method, raw_path, req_schema, {})
            contracts_created += 1
        else:
            # Fallback: extract generic REST endpoint from filename
            endpoint_slug = filename.replace(".bru", "").replace(".txt", "").lower()
            create_api_contract(str(_uuid.uuid4()), service_id, "GET", f"/api/{endpoint_slug}", {}, {})
            contracts_created += 1

    return ok({"service": service_name, "contracts_created": contracts_created, "format": "bruno" if filename.endswith(".bru") else "postman"},
              f"Successfully imported {contracts_created} API contract(s) from {filename}", 201)
