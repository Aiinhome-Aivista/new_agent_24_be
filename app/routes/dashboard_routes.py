from flask import Blueprint
from app.errors.handlers import ok
from app.auth.decorators import require_auth
from app.extensions.db import query

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard/kpis", methods=["GET"])
@require_auth
def kpis():
    def scalar(sql, params=()):
        row = query(sql, params, fetchone=True)
        return list(row.values())[0] if row else 0

    active = scalar("SELECT COUNT(*) c FROM workflow_runs WHERE status NOT IN ('COMPLETED','FAILED','CANCELLED')")
    pending = scalar("SELECT COUNT(*) c FROM approvals WHERE decision='PENDING'")
    executed = scalar("SELECT COALESCE(SUM(total),0) s FROM execution_runs")
    passed = scalar("SELECT COALESCE(SUM(passed),0) s FROM execution_runs")
    evidence_ready = scalar("SELECT COUNT(*) c FROM evidence_packages WHERE approval_status IN ('PENDING','APPROVED')")
    coverage = scalar("SELECT COALESCE(AVG(coverage_pct),0) a FROM stories")
    pass_rate = round((passed / executed * 100), 1) if executed else 0.0

    return ok({"kpis": {
        "active_workflows": active, "pending_approvals": pending,
        "tests_executed": int(executed), "pass_rate": pass_rate,
        "requirement_coverage": round(float(coverage), 1), "evidence_ready": evidence_ready,
    }})


@dashboard_bp.route("/dashboard/activity", methods=["GET"])
@require_auth
def recent_activity():
    workflows = query("""SELECT w.workflow_id, w.status, w.current_stage, s.title AS story_title
                         FROM workflow_runs w JOIN stories s ON s.id=w.story_id
                         ORDER BY w.created_at DESC LIMIT 8""")
    return ok({"recent_workflows": workflows})
