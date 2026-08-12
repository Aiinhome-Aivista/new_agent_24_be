"""
Demo Project & Complete Workflow Runner.
Creates a demo project ('ORD' - Order Management Platform), creates story ORD-101,
acceptance criteria, service, and API contracts, and then executes the complete TDD workflow
through all human checkpoints (TEST_REVIEW, EVIDENCE_REVIEW, ALM_APPROVAL) to DONE.
"""
import sys
import time
import requests
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.extensions.db import query, execute
from app.config import Config
from app import create_app

app = create_app()
client = app.test_client()



def setup_demo_project():
    print("--- 1. Setting up Demo Project (ORD - Order Management Platform) ---")
    
    # Check if project already exists
    existing = query("SELECT * FROM projects WHERE key_code='ORD'", fetchone=True)
    if existing:
        print(f"Project ORD already exists (UUID: {existing['uuid']})")
        project_uuid = existing["uuid"]
        project_id = existing["id"]
    else:
        execute("""
            INSERT INTO projects (uuid, key_code, name, description, target_language, target_framework, coding_standard, health, created_by)
            SELECT UUID(), 'ORD', 'Order Management Platform',
                   'E-commerce microservice handling cart checkout, discount codes, inventory reservations, and order cancellation.',
                   'python', 'pytest', 'pep8', 'green', u.id
            FROM users u WHERE u.email = 'architect@tdd.local'
        """)
        p = query("SELECT * FROM projects WHERE key_code='ORD'", fetchone=True)
        project_uuid = p["uuid"]
        project_id = p["id"]
        print(f"Created project ORD (UUID: {project_uuid})")

    # Map project members
    execute("""
        INSERT IGNORE INTO project_members (project_id, user_id, role_code)
        SELECT %s, u.id,
          CASE u.email
            WHEN 'architect@tdd.local' THEN 'ARCHITECT'
            WHEN 'developer@tdd.local' THEN 'DEVELOPER'
            WHEN 'reviewer@tdd.local'  THEN 'REVIEWER'
            WHEN 'po@tdd.local'        THEN 'PRODUCT_OWNER'
            WHEN 'qa@tdd.local'        THEN 'QA_ENGINEER'
          END
        FROM users u
        WHERE u.email IN ('architect@tdd.local','developer@tdd.local','reviewer@tdd.local','po@tdd.local','qa@tdd.local')
    """, (project_id,))

    # Check story ORD-101
    story = query("SELECT * FROM stories WHERE external_key='ORD-101'", fetchone=True)
    if not story:
        execute("""
            INSERT INTO stories (uuid, project_id, external_key, title, description, sprint, status, coverage_pct, created_by)
            SELECT UUID(), %s, 'ORD-101',
                   'Apply promotional discount and checkout order',
                   'As a shopper, I want to apply a valid promotional discount code during cart checkout so that the order total is discounted and items are reserved.',
                   'Sprint 1', 'ready', 0.00, u.id
            FROM users u WHERE u.email='po@tdd.local'
        """, (project_id,))
        story = query("SELECT * FROM stories WHERE external_key='ORD-101'", fetchone=True)
        print(f"Created story ORD-101 (UUID: {story['uuid']})")
    else:
        print(f"Story ORD-101 already exists (UUID: {story['uuid']})")

    # Story ORD-102
    story_102 = query("SELECT * FROM stories WHERE external_key='ORD-102'", fetchone=True)
    if not story_102:
        execute("""
            INSERT INTO stories (uuid, project_id, external_key, title, description, sprint, status, coverage_pct, created_by)
            SELECT UUID(), %s, 'ORD-102',
                   'Cancel an unfulfilled order',
                   'As a customer, I want to cancel an order pending fulfillment so that my payment is refunded and stock is restored.',
                   'Sprint 1', 'draft', 0.00, u.id
            FROM users u WHERE u.email='po@tdd.local'
        """, (project_id,))
        print("Created story ORD-102")

    # Acceptance criteria for ORD-101
    acs = query("SELECT * FROM acceptance_criteria WHERE story_id=%s", (story["id"],))
    if not acs:
        execute("""
            INSERT INTO acceptance_criteria (uuid, story_id, ac_key, text) VALUES
            (UUID(), %s, 'AC-1', 'Given a cart with items and valid discount code SAVE20, when checkout is submitted, then total is discounted by 20%% and order confirmation is generated.'),
            (UUID(), %s, 'AC-2', 'Given an expired promo code, when checkout is submitted, then the order is rejected with error code PROMO_EXPIRED.'),
            (UUID(), %s, 'AC-3', 'Given a cart total below minimum order amount ($10), when checkout is submitted, then checkout is blocked with MINIMUM_ORDER_NOT_MET.')
        """, (story["id"], story["id"], story["id"]))
        print("Created acceptance criteria (AC-1, AC-2, AC-3) for ORD-101")

    # Service & API Contracts
    svc = query("SELECT * FROM services WHERE project_id=%s AND name='OrderService'", (project_id,), fetchone=True)
    if not svc:
        execute("""
            INSERT INTO services (uuid, project_id, name, description)
            VALUES (UUID(), %s, 'OrderService', 'Manages cart checkout and order state lifecycle.')
        """, (project_id,))
        svc = query("SELECT * FROM services WHERE project_id=%s AND name='OrderService'", (project_id,), fetchone=True)
        print("Created service OrderService")

    contract = query("SELECT * FROM api_contracts WHERE service_id=%s", (svc["id"],), fetchone=True)
    if not contract:
        execute("""
            INSERT INTO api_contracts (uuid, service_id, method, path, request_schema, response_schema, version)
            VALUES (UUID(), %s, 'POST', '/api/v1/orders/checkout',
                    JSON_OBJECT('cartId', 'string', 'promoCode', 'string', 'paymentMethod', 'string'),
                    JSON_OBJECT('orderId', 'string', 'status', 'string', 'discountAmount', 'number', 'finalTotal', 'number'),
                    'v1')
        """, (svc["id"],))
        print("Created API contract for POST /api/v1/orders/checkout")

    return story["uuid"]


def login(email="admin@tdd.local", password="Passw0rd!"):
    r = client.post("/api/v1/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed: {r.get_json()}"
    return r.get_json()["data"]["access_token"]


def run_complete_workflow(story_uuid, token):
    headers = {"Authorization": f"Bearer {token}"}

    print("\n--- 2. Starting Workflow for ORD-101 ---")
    start_payload = {
        "story_uuid": story_uuid,
        "capabilities": ["Test Generation", "API Execution", "Evidence Generation", "ALM Write-back"]
    }
    r = client.post("/api/v1/workflows", json=start_payload, headers=headers)
    res_data = r.get_json()
    assert r.status_code == 201, f"Start failed: {res_data}"
    data = res_data["data"]
    workflow_id = data["workflow_id"]
    print(f"Started Workflow: {workflow_id} (Status: {data['status']})")

    # Check workflow status and test cases
    status_res = client.get(f"/api/v1/workflows/{workflow_id}/status", headers=headers).get_json()["data"]
    print(f"Current Stage: {status_res['current_stage']} | Status: {status_res['status']}")

    tc_res = client.get(f"/api/v1/workflows/{workflow_id}/test-cases", headers=headers).get_json()["data"]
    print(f"Generated {len(tc_res['test_cases'])} Test Cases:")
    for tc in tc_res["test_cases"]:
        print(f"  - [{tc['test_key']}] {tc['title']} ({tc['priority']})")

    # Fetch Approvals
    print("\n--- 3. Checkpoint 1: TEST_REVIEW Approval ---")
    appr_res = client.get(f"/api/v1/workflows/{workflow_id}/approvals", headers=headers).get_json()["data"]
    pending = [a for a in appr_res["approvals"] if a["decision"] == "PENDING"]
    print(f"Found {len(pending)} pending approval(s)")

    for app in pending:
        print(f"Approving Checkpoint: {app['stage']} (UUID: {app['uuid']})...")
        dec_res = client.post(
            f"/api/v1/approvals/{app['uuid']}/decision",
            json={"decision": "APPROVED", "comment": "Approved test cases for ORD-101 promo checkout"},
            headers=headers
        )
        assert dec_res.status_code == 200, f"Approval failed: {dec_res.get_json()}"
        print(f"Decision recorded: {dec_res.get_json()['data']}")

    # Check stage after Checkpoint 1
    status_res = client.get(f"/api/v1/workflows/{workflow_id}/status", headers=headers).get_json()["data"]
    print(f"\nWorkflow Stage after execution & evidence generation: {status_res['current_stage']} | Status: {status_res['status']}")

    # Check Execution results & Evidence
    exec_res = client.get(f"/api/v1/workflows/{workflow_id}/executions", headers=headers).get_json()["data"]
    print(f"Execution Runs: {len(exec_res['executions'])}")
    for ex in exec_res["executions"]:
        print(f"  - Runner: {ex['runner']}, Passed: {ex['passed']}/{ex['total']}, Environment: {ex['environment']}")

    evid_res = client.get(f"/api/v1/workflows/{workflow_id}/evidence", headers=headers).get_json()["data"]
    print(f"Evidence Packages: {len(evid_res['evidence'])}")
    for ev in evid_res["evidence"]:
        print(f"  - Key: {ev['evidence_key']}, Status: {ev['approval_status']}, Checksum: {ev['checksum'][:16]}..., File: {ev['file_path']}")

    # Checkpoint 2: EVIDENCE_REVIEW
    print("\n--- 4. Checkpoint 2: EVIDENCE_REVIEW Approval ---")
    appr_res = client.get(f"/api/v1/workflows/{workflow_id}/approvals", headers=headers).get_json()["data"]
    pending_ev = [a for a in appr_res["approvals"] if a["decision"] == "PENDING"]
    for app in pending_ev:
        print(f"Approving Checkpoint: {app['stage']} (UUID: {app['uuid']})...")
        dec_res = client.post(
            f"/api/v1/approvals/{app['uuid']}/decision",
            json={"decision": "APPROVED", "comment": "Evidence doc approved and verified"},
            headers=headers
        )
        assert dec_res.status_code == 200, f"Approval failed: {dec_res.get_json()}"
        print(f"Decision recorded: {dec_res.get_json()['data']}")

    # Checkpoint 3: ALM_APPROVAL
    status_res = client.get(f"/api/v1/workflows/{workflow_id}/status", headers=headers).get_json()["data"]
    print(f"\nWorkflow Stage after evidence review: {status_res['current_stage']} | Status: {status_res['status']}")

    print("\n--- 5. Checkpoint 3: ALM_APPROVAL Approval ---")
    appr_res = client.get(f"/api/v1/workflows/{workflow_id}/approvals", headers=headers).get_json()["data"]
    pending_alm = [a for a in appr_res["approvals"] if a["decision"] == "PENDING"]
    for app in pending_alm:
        print(f"Approving Checkpoint: {app['stage']} (UUID: {app['uuid']})...")
        dec_res = client.post(
            f"/api/v1/approvals/{app['uuid']}/decision",
            json={"decision": "APPROVED", "comment": "Approved ALM attachment to external tracking"},
            headers=headers
        )
        assert dec_res.status_code == 200, f"Approval failed: {dec_res.get_json()}"
        print(f"Decision recorded: {dec_res.get_json()['data']}")

    # Final State Check
    final_res = client.get(f"/api/v1/workflows/{workflow_id}", headers=headers).get_json()["data"]
    wf = final_res["workflow"]
    agent_runs = final_res["agent_runs"]

    print(f"\n=======================================================")
    print(f" WORKFLOW COMPLETED SUCCESSFULLY!")
    print(f"=======================================================")
    print(f" Workflow ID   : {wf['workflow_id']}")
    print(f" Final Stage   : {wf['current_stage']}")
    print(f" Final Status  : {wf['status']}")
    print(f" Agent Runs    : {len(agent_runs)} steps executed")
    for ar in agent_runs:
        print(f"   * {ar['agent']} ({ar['task_type']}) -> Status: {ar['status']}, Latency: {ar['latency_ms']}ms")
    print(f"=======================================================\n")



def main():
    story_uuid = setup_demo_project()
    token = login()
    run_complete_workflow(story_uuid, token)


if __name__ == "__main__":
    main()
