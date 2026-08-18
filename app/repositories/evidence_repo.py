"""Evidence + approval persistence."""
import json
from app.extensions.db import query, execute


def insert_evidence(uuid, evidence_key, workflow_id, story_id, fmt, file_path, checksum,
                    source_execution_ids, prompt_version, model_info, narrative):
    return execute("""INSERT INTO evidence_packages
        (uuid, evidence_key, workflow_id, story_id, format, file_path, checksum,
         source_execution_ids, prompt_version, model_info, narrative, approval_status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING')""",
        (uuid, evidence_key, workflow_id, story_id, fmt, file_path, checksum,
         json.dumps(source_execution_ids or [], default=str), prompt_version,
         json.dumps(model_info or {}, default=str), narrative), return_id=True)



def get_evidence(uuid):
    return query("SELECT * FROM evidence_packages WHERE uuid=%s", (uuid,), fetchone=True)


def list_evidence(workflow_id):
    return query("SELECT * FROM evidence_packages WHERE workflow_id=%s ORDER BY created_at DESC", (workflow_id,))


def set_evidence_status(uuid, status):
    execute("UPDATE evidence_packages SET approval_status=%s WHERE uuid=%s", (status, uuid))


def create_approval(uuid, workflow_id, stage, decision="PENDING"):
    execute("""INSERT INTO approvals (uuid, workflow_id, stage, decision)
               VALUES (%s,%s,%s,%s)""", (uuid, workflow_id, stage, decision))


def decide_approval(uuid, decision, approver_id, comment):
    execute("""UPDATE approvals SET decision=%s, approver_id=%s, comment=%s, decided_at=NOW()
               WHERE uuid=%s""", (decision, approver_id, comment, uuid))


def pending_approvals():
    return query("""SELECT a.*, w.story_id, w.project_id, p.uuid AS project_uuid, p.name AS project_name,
                           p.key_code AS project_key, s.title AS story_title
                    FROM approvals a
                    JOIN workflow_runs w ON w.workflow_id=a.workflow_id
                    LEFT JOIN projects p ON p.id=w.project_id
                    LEFT JOIN stories s ON s.id=w.story_id
                    WHERE a.decision='PENDING' ORDER BY a.requested_at ASC""")


def approvals_for(workflow_id):
    return query("""SELECT a.*, u.name AS approver_name
                    FROM approvals a
                    LEFT JOIN users u ON u.id=a.approver_id
                    WHERE a.workflow_id=%s ORDER BY a.requested_at ASC""", (workflow_id,))


def find_alm_writeback(idempotency_key):
    return query("SELECT status FROM alm_writebacks WHERE idempotency_key=%s",
                 (idempotency_key,), fetchone=True)


def latest_evidence_row(workflow_id):
    return query("""SELECT id, uuid, evidence_key FROM evidence_packages
                    WHERE workflow_id=%s ORDER BY id DESC LIMIT 1""", (workflow_id,), fetchone=True)


def record_alm_writeback(uuid, workflow_id, story_id, evidence_id, idempotency_key,
                         request_id, external_ref, status, response, is_mock):
    import json
    execute("""INSERT INTO alm_writebacks
        (uuid, workflow_id, story_id, evidence_id, idempotency_key, request_id, external_ref, status, response, is_mock)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (uuid, workflow_id, story_id, evidence_id, idempotency_key, request_id, external_ref,
         status, json.dumps(response or {}, default=str), 1 if is_mock else 0))

