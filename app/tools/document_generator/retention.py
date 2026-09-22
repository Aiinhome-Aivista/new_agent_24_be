import os
import glob
from app.extensions.db import query


def cleanup_old_evidence():
    """
    Strict temporary evidence lifecycle cleanup:
    1. A .docx evidence file is strictly TEMPORARY on local disk.
    2. Once a workflow is COMPLETED (uploaded to Jira), CANCELLED, or FAILED,
       its local .docx file is no longer needed and is automatically deleted.
    3. If evidence is marked ATTACHED (synced to Jira/ALM), it is automatically deleted.
    4. For any active workflow (e.g. WAITING_FOR_APPROVAL), only the single LATEST
       active evidence .docx is kept until human approval/Jira sync. Any older superseded
       drafts from re-runs are automatically deleted.
    5. All stray non-docx files (.html, .md, .json) and PNG snapshots are purged.
    """
    try:
        out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "evidence_output"))
        if not os.path.isdir(out_dir):
            return

        # 1. Identify ONLY active pending workflows awaiting review/approval
        active_workflows = query(
            "SELECT workflow_id FROM workflow_runs WHERE status IN ('WAITING_FOR_APPROVAL', 'WAITING_FOR_REVIEW', 'RUNNING', 'VALIDATING', 'GENERATING_EVIDENCE')"
        ) or []
        active_ids = [w["workflow_id"] for w in active_workflows]

        # 2. For active workflows, find only the SINGLE LATEST unattached evidence key
        keep_keys = set()
        if active_ids:
            placeholders = ",".join(["%s"] * len(active_ids))
            active_evidence = query(
                f"""
                SELECT workflow_id, evidence_key, approval_status, created_at
                FROM evidence_packages
                WHERE workflow_id IN ({placeholders}) AND approval_status != 'ATTACHED'
                ORDER BY created_at DESC
                """,
                tuple(active_ids)
            ) or []

            seen_workflows = set()
            for row in active_evidence:
                wf_id = row.get("workflow_id")
                ev_key = row.get("evidence_key")
                if wf_id not in seen_workflows and ev_key:
                    seen_workflows.add(wf_id)
                    keep_keys.add(ev_key)

        # 3. Purge non-docx and unneeded/historical/orphaned .docx files
        for file_path in glob.glob(os.path.join(out_dir, "*.*")):
            filename = os.path.basename(file_path)
            base_name, ext = os.path.splitext(filename)

            # Purge temporary md or json files immediately
            if ext.lower() in (".md", ".json"):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
                continue

            # For docx and html evidence files: keep active evidence matching keep_keys
            if ext.lower() in (".docx", ".html"):
                is_currently_needed = any(k in base_name for k in keep_keys)
                if not is_currently_needed:
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass

        # 4. Clean up any leftover temporary PNG snapshots
        snap_dir = os.path.join(out_dir, "snapshots")
        if os.path.isdir(snap_dir):
            for png in glob.glob(os.path.join(snap_dir, "*.png")):
                try:
                    os.remove(png)
                except Exception:
                    pass

        # 5. Clean up any accidental docx files in workspace root
        ws_dir = os.path.abspath(os.path.join(out_dir, ".."))
        for stray in glob.glob(os.path.join(ws_dir, "EVID-*.docx")):
            try:
                os.remove(stray)
            except Exception:
                pass

        # 6. Clean up temporary generated_tests directory:
        # Only keep test folders for currently active workflows.
        # Completed, cancelled, failed, or mock folders are automatically deleted.
        gen_tests_dir = os.path.join(out_dir, "generated_tests")
        if os.path.isdir(gen_tests_dir):
            import shutil
            for entry in os.listdir(gen_tests_dir):
                entry_path = os.path.join(gen_tests_dir, entry)
                if os.path.isdir(entry_path):
                    if entry not in active_ids:
                        try:
                            shutil.rmtree(entry_path, ignore_errors=True)
                        except Exception:
                            pass

    except Exception as e:
        print(f"[Retention] Notice: evidence cleanup skipped: {e}")
