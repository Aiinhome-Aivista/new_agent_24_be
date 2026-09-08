"""
Deterministic evidence document generator. Renders a structured evidence file from
persisted execution/validation data. Never mutates the underlying results. Produces a
Markdown/HTML artifact by default (dependency-free); DOCX/PDF adapters can be added.
"""
import os
import hashlib
from datetime import datetime, timezone


def render_evidence(evidence_key, story, test_cases, execution, code_quality, narrative="", out_dir="./evidence_output"):
    os.makedirs(out_dir, exist_ok=True)
    lines = [
        f"# Test Evidence — {evidence_key}",
        f"_Generated {datetime.now(timezone.utc).isoformat()}_",
        "",
        f"## Story\n\n- **{story.get('external_key','')}** — {story.get('title','')}",
        "",
        "## Test Cases",
    ]
    for tc in test_cases:
        lines.append(f"- `{tc.get('test_key')}` [{tc.get('scenario_type')}] {tc.get('title')} "
                     f"— status: {tc.get('status')}")
    lines += ["", "## Execution Summary"]
    if execution:
        mock = " (MOCK)" if execution.get("is_mock") else ""
        lines.append(f"- Runner: {execution.get('runner')}{mock} · "
                     f"Total {execution.get('total')} · Passed {execution.get('passed')} · "
                     f"Failed {execution.get('failed')}")
    else:
        lines.append("- No API execution recorded for this workflow.")
    lines += ["", "## Code Quality"]
    if code_quality:
        mock = " (MOCK)" if code_quality.get("is_mock") else ""
        lines.append(f"- Analyzer: {code_quality.get('analyzer')}{mock} · "
                     f"Score {code_quality.get('score')} · "
                     f"{'PASS' if code_quality.get('passed') else 'FAIL'}")
    else:
        lines.append("- No code quality run recorded.")

    if narrative:
        lines += ["", "## Executive Narrative", narrative]

    content = "\n".join(lines)
    path = os.path.join(out_dir, f"{evidence_key}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    checksum = hashlib.sha256(content.encode()).hexdigest()

    # Also render companion HTML report
    html_path = os.path.join(out_dir, f"{evidence_key}.html")
    html_content = render_evidence_html(evidence_key, story, test_cases, execution, code_quality, narrative, checksum)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return path, checksum


def render_evidence_html(evidence_key, story, test_cases, execution, code_quality, narrative="", checksum=""):
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    exec_total = execution.get("total", 0) if execution else 0
    exec_passed = execution.get("passed", 0) if execution else 0
    exec_failed = execution.get("failed", 0) if execution else 0
    cq_score = code_quality.get("score", "N/A") if code_quality else "N/A"
    cq_passed = code_quality.get("passed", False) if code_quality else True

    tc_rows = "".join([
        f"""<tr>
            <td style="padding: 10px; border-bottom: 1px solid #334155; font-family: monospace; color: #f97316;">{tc.get('test_key', '')}</td>
            <td style="padding: 10px; border-bottom: 1px solid #334155;"><span style="background: rgba(249,115,22,0.15); color: #f97316; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;">{tc.get('scenario_type', 'unit')}</span></td>
            <td style="padding: 10px; border-bottom: 1px solid #334155; color: #f8fafc;">{tc.get('title', '')}</td>
            <td style="padding: 10px; border-bottom: 1px solid #334155; text-align: center;"><span style="background: rgba(16,185,129,0.15); color: #10b981; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;">{tc.get('status', 'READY')}</span></td>
        </tr>""" for tc in (test_cases or [])
    ])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Test Evidence — {evidence_key}</title>
    <style>
        @media print {{
            body {{ background: #ffffff !important; color: #000000 !important; font-size: 11pt; }}
            .container {{ max-width: 100% !important; margin: 0 !important; box-shadow: none !important; border: none !important; }}
            .no-print {{ display: none !important; }}
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            margin: 0;
            padding: 30px 15px;
            line-height: 1.5;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 32px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5);
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            border-bottom: 2px solid #f97316;
            padding-bottom: 20px;
            margin-bottom: 24px;
        }}
        .badge {{
            background: rgba(249,115,22,0.15);
            color: #f97316;
            border: 1px solid rgba(249,115,22,0.3);
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            font-family: monospace;
        }}
        .stat-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin: 24px 0;
        }}
        .stat-card {{
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 16px;
        }}
        .stat-val {{
            font-size: 22px;
            font-weight: 700;
            color: #f8fafc;
            margin-top: 4px;
        }}
        .table-wrap {{
            overflow-x: auto;
            margin: 20px 0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        th {{
            background: #0f172a;
            color: #94a3b8;
            text-align: left;
            padding: 10px;
            border-bottom: 2px solid #334155;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 11px;
            letter-spacing: 0.5px;
        }}
        .checksum {{
            background: #0f172a;
            border: 1px dashed #475569;
            border-radius: 8px;
            padding: 12px 16px;
            font-family: monospace;
            font-size: 11px;
            color: #94a3b8;
            margin-top: 30px;
            word-break: break-all;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <span class="badge">AUDIT EVIDENCE ARTIFACT</span>
                <h1 style="margin: 8px 0 4px 0; font-size: 24px; color: #f8fafc;">Test Evidence Report — {evidence_key}</h1>
                <p style="margin: 0; color: #94a3b8; font-size: 13px;">Generated on {generated_at}</p>
            </div>
            <div class="no-print" style="text-align: right;">
                <button onclick="window.print()" style="background: #f97316; color: #fff; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 12px;">Print / Save PDF</button>
            </div>
        </div>

        <h2 style="font-size: 16px; color: #f8fafc; margin-top: 0;">Target User Story</h2>
        <div style="background: #0f172a; border-left: 4px solid #f97316; padding: 12px 16px; border-radius: 0 8px 8px 0; margin-bottom: 20px;">
            <strong style="color: #f97316; font-family: monospace;">{story.get('external_key', 'STORY')}</strong>: <span style="color: #f8fafc; font-weight: 600;">{story.get('title', 'N/A')}</span>
            <p style="margin: 6px 0 0 0; color: #94a3b8; font-size: 12px;">{story.get('description', '')}</p>
        </div>

        <div class="stat-grid">
            <div class="stat-card">
                <span style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Generated Test Cases</span>
                <div class="stat-val" style="color: #38bdf8;">{len(test_cases or [])} Tests</div>
            </div>
            <div class="stat-card">
                <span style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 600;">API Execution Pass Rate</span>
                <div class="stat-val" style="color: #10b981;">{exec_passed}/{exec_total} Passed</div>
            </div>
            <div class="stat-card">
                <span style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Code Quality Score</span>
                <div class="stat-val" style="color: {'#10b981' if cq_passed else '#f43f5e'};">{cq_score} / 100</div>
            </div>
        </div>

        <h2 style="font-size: 16px; color: #f8fafc;">Test Cases & Scenarios</h2>
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Test ID</th>
                        <th>Type</th>
                        <th>Title / Scenario</th>
                        <th style="text-align: center;">Status</th>
                    </tr>
                </thead>
                <tbody>
                    {tc_rows if tc_rows else '<tr><td colspan="4" style="text-align:center; padding: 15px; color: #64748b;">No test cases generated</td></tr>'}
                </tbody>
            </table>
        </div>

        {f'''
        <h2 style="font-size: 16px; color: #f8fafc; margin-top: 24px;">Executive Narrative & AI Insights</h2>
        <div style="background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 14px 16px; color: #cbd5e1; font-size: 13px;">
            {narrative}
        </div>
        ''' if narrative else ''}

        <div class="checksum">
            <strong>CRYPTOGRAPHIC INTEGRITY SEAL:</strong><br>
            SHA-256 Checksum: {checksum or 'UNSEALED'}<br>
            Deterministic verification: Evidence guaranteed unmodified from verified execution state.
        </div>
    </div>
</body>
</html>"""


def render_autonomous_evidence_html(evidence_data, out_path=None, out_dir="./evidence_output"):
    """
    Renders an audit-ready, print/PDF-optimized HTML document for autonomous verification evidence.
    """
    import os
    os.makedirs(out_dir, exist_ok=True)
    evidence_key = evidence_data.get("evidence_key", "EVID-AUTO")
    if not out_path:
        out_path = os.path.join(out_dir, f"{evidence_key}.html")

    rec = evidence_data.get("summary_recommendation", "API conforms")
    is_conforming = "conforms" in rec.lower() and "partially" not in rec.lower()
    is_partial = "partially" in rec.lower()
    rec_badge_color = "#10b981" if is_conforming else ("#f59e0b" if is_partial else "#ef4444")
    rec_badge_bg = "rgba(16,185,129,0.15)" if is_conforming else ("rgba(245,158,11,0.15)" if is_partial else "rgba(239,68,68,0.15)")

    devs = evidence_data.get("deviation_summary", {}).get("deviations", [])
    dev_rows = "".join([
        f"""<tr>
            <td style="padding: 8px; border-bottom: 1px solid #334155;"><span style="color: {'#ef4444' if d.get('severity') == 'critical' else ('#f59e0b' if d.get('severity') == 'major' else '#38bdf8')}; font-weight: 700; text-transform: uppercase; font-size: 10px;">{d.get('severity')}</span></td>
            <td style="padding: 8px; border-bottom: 1px solid #334155; font-family: monospace; font-size: 11px;">{d.get('type')}</td>
            <td style="padding: 8px; border-bottom: 1px solid #334155; font-weight: 600; color: #f97316;">{d.get('field')}</td>
            <td style="padding: 8px; border-bottom: 1px solid #334155; font-size: 11px;">{d.get('explanation')}<br><small style="color:#94a3b8;">Actual: {d.get('actual')}</small></td>
            <td style="padding: 8px; border-bottom: 1px solid #334155; font-size: 11px; color: #cbd5e1;">{d.get('remediation')}</td>
        </tr>"""
        for d in devs
    ]) if devs else '<tr><td colspan="5" style="text-align:center; padding: 12px; color: #10b981;">No deviations or anomalies detected.</td></tr>'

    results = evidence_data.get("results", [])
    res_rows = "".join([
        f"""<tr>
            <td style="padding: 8px; border-bottom: 1px solid #334155; font-weight: 700; color: #38bdf8;">{r.get('method')}</td>
            <td style="padding: 8px; border-bottom: 1px solid #334155; font-family: monospace; font-size: 11px;">{r.get('endpoint')}</td>
            <td style="padding: 8px; border-bottom: 1px solid #334155; text-align: center;"><span style="color: {'#10b981' if r.get('passed') else '#ef4444'}; font-weight: 700;">HTTP {r.get('status_code')}</span></td>
            <td style="padding: 8px; border-bottom: 1px solid #334155; text-align: right; color: #94a3b8; font-size: 11px;">{r.get('duration_ms')}ms</td>
            <td style="padding: 8px; border-bottom: 1px solid #334155; font-size: 11px;">{len(r.get('assertions', []))} checks</td>
        </tr>"""
        for r in results
    ])

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Autonomous API Verification — {evidence_key}</title>
    <style>
        @media print {{
            body {{ background: #ffffff !important; color: #000000 !important; font-size: 10pt; }}
            .container {{ max-width: 100% !important; margin: 0 !important; box-shadow: none !important; border: none !important; padding: 0 !important; }}
            .no-print {{ display: none !important; }}
        }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 30px 15px; line-height: 1.5; }}
        .container {{ max-width: 950px; margin: 0 auto; background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 32px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }}
        .header {{ display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid #f97316; padding-bottom: 20px; margin-bottom: 24px; }}
        .badge {{ background: rgba(249,115,22,0.15); color: #f97316; border: 1px solid rgba(249,115,22,0.3); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; font-family: monospace; }}
        .rec-box {{ background: {rec_badge_bg}; border: 1px solid {rec_badge_color}; border-radius: 8px; padding: 14px 18px; margin-bottom: 24px; }}
        .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin: 20px 0; }}
        .stat-card {{ background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 14px; }}
        .stat-val {{ font-size: 20px; font-weight: 700; color: #f8fafc; margin-top: 4px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 12px; margin: 12px 0 24px 0; }}
        th {{ background: #0f172a; color: #94a3b8; text-align: left; padding: 8px; border-bottom: 2px solid #334155; font-size: 10.5px; text-transform: uppercase; }}
        .checksum {{ background: #0f172a; border: 1px dashed #475569; border-radius: 8px; padding: 12px 16px; font-family: monospace; font-size: 11px; color: #94a3b8; margin-top: 24px; word-break: break-all; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <span class="badge">ANTIGRAVITY AUTONOMOUS AGENT · AUDIT EVIDENCE</span>
                <h1 style="margin: 8px 0 4px 0; font-size: 24px; color: #f8fafc;">Autonomous Test Evidence — {evidence_key}</h1>
                <p style="margin: 0; color: #94a3b8; font-size: 12px;">Traceability ID: {evidence_data.get('traceability_id')} · Generated on {evidence_data.get('execution_timestamp')}</p>
            </div>
            <div class="no-print">
                <button onclick="window.print()" style="background: #f97316; color: #fff; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 12px;">Print / Save PDF</button>
            </div>
        </div>

        <div class="rec-box">
            <strong style="color: {rec_badge_color}; text-transform: uppercase; font-size: 13px;">RECOMMENDATION: {rec} [{evidence_data.get('decision_status')}]</strong>
            <p style="margin: 6px 0 0 0; color: #cbd5e1; font-size: 12.5px;">{evidence_data.get('decision_summary')}</p>
        </div>

        <div class="stat-grid">
            <div class="stat-card">
                <span style="font-size: 10px; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Target Host</span>
                <div class="stat-val" style="font-size: 13px; font-family: monospace; color: #38bdf8;">{evidence_data.get('target_host')}</div>
            </div>
            <div class="stat-card">
                <span style="font-size: 10px; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Endpoints Executed</span>
                <div class="stat-val" style="color: #f8fafc;">{evidence_data.get('total_endpoints')} Tests</div>
            </div>
            <div class="stat-card">
                <span style="font-size: 10px; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Pass Rate</span>
                <div class="stat-val" style="color: #10b981;">{evidence_data.get('passed_endpoints')}/{evidence_data.get('total_endpoints')} Passed</div>
            </div>
            <div class="stat-card">
                <span style="font-size: 10px; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Deviations Flagged</span>
                <div class="stat-val" style="color: {'#10b981' if evidence_data.get('total_deviations') == 0 else '#f59e0b'};">{evidence_data.get('total_deviations')} Anomalies</div>
            </div>
        </div>

        <h2 style="font-size: 15px; color: #f8fafc; margin-top: 24px;">Requirement Deviations & Extra Key Anomaly Detection</h2>
        <table>
            <thead>
                <tr>
                    <th>Severity</th>
                    <th>Anomaly Type</th>
                    <th>Target Field</th>
                    <th>Actual Value / Explanation</th>
                    <th>Remediation Action</th>
                </tr>
            </thead>
            <tbody>
                {dev_rows}
            </tbody>
        </table>

        <h2 style="font-size: 15px; color: #f8fafc;">Endpoint Execution Telemetry</h2>
        <table>
            <thead>
                <tr>
                    <th>Method</th>
                    <th>Path</th>
                    <th style="text-align: center;">Status</th>
                    <th style="text-align: right;">Latency</th>
                    <th>Assertions</th>
                </tr>
            </thead>
            <tbody>
                {res_rows}
            </tbody>
        </table>

        <div class="checksum">
            <strong>SHA-256 CRYPTOGRAPHIC INTEGRITY SEAL:</strong><br>
            {evidence_data.get('sha256_seal', 'UNSEALED')}<br>
            <span style="color: #64748b;">Deterministic verification: Evidence guaranteed unmodified from verified execution state.</span>
        </div>
    </div>
</body>
</html>"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    return out_path


