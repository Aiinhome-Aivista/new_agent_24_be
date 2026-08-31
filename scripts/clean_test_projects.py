import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.extensions.db import execute, query

test_ids = [p['id'] for p in query("SELECT id FROM projects WHERE description IN ('Alpha service', 'Beta service')")]
if test_ids:
    id_list = ",".join(str(i) for i in test_ids)
    print(f"Cleaning {len(test_ids)} projects...", flush=True)
    execute(f"DELETE FROM test_cases WHERE workflow_id IN (SELECT workflow_id FROM workflow_runs WHERE project_id IN ({id_list}))")
    execute(f"DELETE FROM workflow_tasks WHERE workflow_id IN (SELECT workflow_id FROM workflow_runs WHERE project_id IN ({id_list}))")
    execute(f"DELETE FROM workflow_runs WHERE project_id IN ({id_list})")
    execute(f"DELETE FROM acceptance_criteria WHERE story_id IN (SELECT id FROM stories WHERE project_id IN ({id_list}))")
    execute(f"DELETE FROM stories WHERE project_id IN ({id_list})")
    execute(f"DELETE FROM knowledge_chunks WHERE document_id IN (SELECT id FROM knowledge_documents WHERE project_id IN ({id_list}))")
    execute(f"DELETE FROM knowledge_documents WHERE project_id IN ({id_list})")
    execute(f"DELETE FROM api_contracts WHERE service_id IN (SELECT id FROM services WHERE project_id IN ({id_list}))")
    execute(f"DELETE FROM services WHERE project_id IN ({id_list})")
    execute(f"DELETE FROM project_members WHERE project_id IN ({id_list})")
    execute(f"DELETE FROM projects WHERE id IN ({id_list})")
    print("All test projects cleaned up successfully!", flush=True)
else:
    print("No test projects to clean.", flush=True)
