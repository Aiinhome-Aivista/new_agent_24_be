"""Project, story, contract, and knowledge repository data access."""
import json
import uuid as _uuid
from app.extensions.db import query, execute


def list_projects():
    return query("""SELECT p.*,
                     (SELECT COUNT(*) FROM stories s WHERE s.project_id=p.id) AS story_count,
                     (SELECT COUNT(*) FROM workflow_runs w WHERE w.project_id=p.id AND w.status NOT IN ('COMPLETED','FAILED','CANCELLED')) AS active_workflows
                    FROM projects p ORDER BY p.created_at DESC""")


def get_project(uuid):
    return query("SELECT * FROM projects WHERE uuid=%s", (uuid,), fetchone=True)


def get_project_by_id(project_id):
    return query("SELECT * FROM projects WHERE id=%s", (project_id,), fetchone=True)


def create_project(uuid, key_code, name, description, target_language="java", target_framework="junit5", coding_standard="checkstyle-google", created_by=None,
                   git_repo_url=None, git_provider=None, git_branch="main", base_branch="main", tech_stack=None, build_tool=None,
                   app_type="REST API / Microservice", deployment_target=None, testing_framework=None, integration_test_framework=None,
                   mocking_library=None, target_coverage="80%", frontend_framework=None, backend_framework=None):
    return execute("""
        INSERT INTO projects
        (uuid, key_code, name, description, target_language, target_framework, coding_standard, health, created_by,
         git_repo_url, git_provider, git_branch, base_branch, tech_stack, build_tool, app_type, deployment_target,
         testing_framework, integration_test_framework, mocking_library, target_coverage, frontend_framework, backend_framework)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'green', %s,
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s)
    """, (uuid, key_code.upper().strip(), name.strip(), description, target_language, target_framework, coding_standard, created_by,
          git_repo_url, git_provider, git_branch, base_branch, tech_stack, build_tool, app_type, deployment_target,
          testing_framework or target_framework, integration_test_framework, mocking_library, target_coverage,
          frontend_framework, backend_framework), return_id=True)


def list_stories(project_uuid=None):
    if project_uuid:
        return query("""SELECT s.*, p.uuid AS project_uuid, p.key_code AS project_key, p.name AS project_name
                        FROM stories s JOIN projects p ON p.id=s.project_id
                        WHERE p.uuid=%s ORDER BY s.created_at DESC""", (project_uuid,))
    return query("""SELECT s.*, p.uuid AS project_uuid, p.key_code AS project_key, p.name AS project_name
                    FROM stories s JOIN projects p ON p.id=s.project_id
                    ORDER BY s.created_at DESC""")


def get_story(uuid):
    return query("""SELECT s.*, p.uuid AS project_uuid, p.key_code AS project_key, p.name AS project_name
                    FROM stories s JOIN projects p ON p.id=s.project_id
                    WHERE s.uuid=%s""", (uuid,), fetchone=True)


def create_story(uuid, project_id, external_key, title, description, sprint="Sprint 1", created_by=None):
    return execute("""
        INSERT INTO stories
        (uuid, project_id, external_key, title, description, sprint, status, coverage_pct, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, 'ready', 0.00, %s)
    """, (uuid, project_id, external_key, title, description, sprint, created_by), return_id=True)


def story_acceptance_criteria(story_id):
    return query("SELECT uuid, ac_key, text, created_at FROM acceptance_criteria WHERE story_id=%s ORDER BY ac_key", (story_id,))


def create_acceptance_criterion(uuid, story_id, ac_key, text):
    return execute("""
        INSERT INTO acceptance_criteria (uuid, story_id, ac_key, text)
        VALUES (%s, %s, %s, %s)
    """, (uuid, story_id, ac_key, text), return_id=True)


def list_knowledge_documents(project_id):
    return query("""
        SELECT d.*, u.name AS uploader_name
        FROM knowledge_documents d
        LEFT JOIN users u ON u.id=d.uploaded_by
        WHERE d.project_id=%s
        ORDER BY d.created_at DESC
    """, (project_id,))


def get_knowledge_document(uuid):
    return query("SELECT * FROM knowledge_documents WHERE uuid=%s", (uuid,), fetchone=True)


def list_services_and_contracts(project_id):
    services = query("SELECT * FROM services WHERE project_id=%s ORDER BY name ASC", (project_id,))
    contracts = query("""
        SELECT c.*, s.name AS service_name
        FROM api_contracts c
        JOIN services s ON s.id=c.service_id
        WHERE s.project_id=%s
        ORDER BY s.name, c.path
    """, (project_id,))
    return {"services": services, "contracts": contracts}


def create_service(uuid, project_id, name, description):
    return execute("""
        INSERT INTO services (uuid, project_id, name, description)
        VALUES (%s, %s, %s, %s)
    """, (uuid, project_id, name, description), return_id=True)


def create_api_contract(uuid, service_id, method, path, request_schema=None, response_schema=None, version="v1"):
    return execute("""
        INSERT INTO api_contracts (uuid, service_id, method, path, request_schema, response_schema, version)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (uuid, service_id, method.upper(), path, json.dumps(request_schema or {}, default=str), json.dumps(response_schema or {}, default=str), version), return_id=True)
