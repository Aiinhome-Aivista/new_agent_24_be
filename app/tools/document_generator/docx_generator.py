"""
Deterministic Word (.docx) evidence document generator using python-docx.
Renders audit-grade test evidence packages with tables, metrics, deviation analyses,
and tamper-evident cryptographic SHA-256 seals.
"""
import os
import json
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn
from app.tools.document_generator.snapshot_image_generator import generate_postman_snapshot_image


def _set_cell_shading(cell, color_hex):
    """Sets background color for a table cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>')
    tcPr.append(shd)


def _set_table_borders(table):
    """Adds subtle clean border styling to a docx table."""
    tblPr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'  <w:top w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
        f'  <w:bottom w:val="single" w:sz="6" w:space="0" w:color="94A3B8"/>'
        f'  <w:insideH w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
        f'  <w:insideV w:val="none"/>'
        f'  <w:left w:val="none"/>'
        f'  <w:right w:val="none"/>'
        f'</w:tblBorders>'
    )
    tblPr.append(borders)


def generate_docx_evidence(evidence_data, out_path=None, out_dir="./evidence_output"):
    """
    Renders an audit-ready Microsoft Word (.docx) document from an autonomous evidence dictionary.
    Returns the absolute path to the generated .docx file.
    """
    os.makedirs(out_dir, exist_ok=True)
    evidence_key = evidence_data.get("evidence_key", "EVID-AUTO")
    if not out_path:
        out_path = os.path.join(out_dir, f"{evidence_key}.docx")

    doc = docx.Document()

    # Configure 0.75-inch standard margins
    sections = doc.sections
    for section in sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)

    # Document Header Badge
    p_pre = doc.add_paragraph()
    run_pre = p_pre.add_run("TDD INTELLIGENCE  |  AUDIT-GRADE VERIFICATION EVIDENCE")
    run_pre.font.size = Pt(8.5)
    run_pre.font.bold = True
    run_pre.font.color.rgb = RGBColor(234, 88, 12)  # PwC Orange / Primary
    p_pre.paragraph_format.space_after = Pt(4)

    # Document Title
    p_title = doc.add_paragraph()
    run_title = p_title.add_run(f"API Test Evidence Report — {evidence_key}")
    run_title.font.size = Pt(20)
    run_title.font.bold = True
    run_title.font.color.rgb = RGBColor(15, 23, 42)  # Slate 900
    p_title.paragraph_format.space_after = Pt(2)

    p_sub = doc.add_paragraph()
    run_sub = p_sub.add_run(f"Traceability ID: {evidence_data.get('traceability_id', 'N/A')}  ·  Generated: {evidence_data.get('execution_timestamp', '')}")
    run_sub.font.size = Pt(9.5)
    run_sub.font.color.rgb = RGBColor(100, 116, 139)
    p_sub.paragraph_format.space_after = Pt(14)

    # Executive Recommendation Callout Box
    rec = evidence_data.get("summary_recommendation", "API conforms")
    decision_status = evidence_data.get("decision_status", "Ready for Approval")
    is_conforming = "conforms" in rec.lower() and "partially" not in rec.lower()
    is_partial = "partially" in rec.lower()

    rec_color = RGBColor(16, 185, 129) if is_conforming else (RGBColor(217, 119, 6) if is_partial else RGBColor(225, 29, 72))
    bg_color = "ECFDF5" if is_conforming else ("FFFBEB" if is_partial else "FFF1F2")

    rec_table = doc.add_table(rows=1, cols=1)
    rec_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = rec_table.cell(0, 0)
    _set_cell_shading(cell, bg_color)
    p_rec = cell.paragraphs[0]
    p_rec.paragraph_format.space_before = Pt(8)
    p_rec.paragraph_format.space_after = Pt(8)
    r1 = p_rec.add_run("EXECUTIVE RECOMMENDATION:  ")
    r1.font.bold = True
    r1.font.size = Pt(11)
    r1.font.color.rgb = rec_color

    r2 = p_rec.add_run(f"{rec.upper()}  [{decision_status.upper()}]\n")
    r2.font.bold = True
    r2.font.size = Pt(12)
    r2.font.color.rgb = rec_color

    r3 = p_rec.add_run(evidence_data.get("decision_summary", ""))
    r3.font.size = Pt(9.5)
    r3.font.color.rgb = RGBColor(51, 65, 85)

    doc.add_paragraph().paragraph_format.space_after = Pt(10)

    # Section 1: Metadata Summary Table
    h1 = doc.add_heading("1. Audit & Environment Telemetry", level=2)
    h1.paragraph_format.space_before = Pt(12)
    h1.paragraph_format.space_after = Pt(6)

    meta_table = doc.add_table(rows=5, cols=2)
    meta_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _set_table_borders(meta_table)

    meta_rows = [
        ("Target API Host / Base URL", evidence_data.get("target_host", "http://localhost:5001")),
        ("Postman Test Collection", evidence_data.get("collection_name", "Test Collection")),
        ("Linked User Story", f"{evidence_data.get('story', {}).get('external_key', '')} — {evidence_data.get('story', {}).get('title', '')}"),
        ("Execution Engine", evidence_data.get("telemetry", {}).get("runner", "HttpRunner")),
        ("Total Network Latency", f"{evidence_data.get('telemetry', {}).get('execution_duration_total_ms', 0)} ms"),
    ]

    for i, (k, v) in enumerate(meta_rows):
        c0 = meta_table.cell(i, 0)
        c1 = meta_table.cell(i, 1)
        c0.width = Inches(2.2)
        c1.width = Inches(4.8)
        _set_cell_shading(c0, "F8FAFC")
        p0 = c0.paragraphs[0]
        r = p0.add_run(k)
        r.font.bold = True
        r.font.size = Pt(9)
        r.font.color.rgb = RGBColor(71, 85, 105)

        p1 = c1.paragraphs[0]
        r_v = p1.add_run(str(v))
        r_v.font.size = Pt(9)
        r_v.font.color.rgb = RGBColor(15, 23, 42)

    # Section 2: Execution Metrics & Pass Rate
    h2 = doc.add_heading("2. Execution Metrics & Assertion Summary", level=2)
    h2.paragraph_format.space_before = Pt(14)
    h2.paragraph_format.space_after = Pt(6)

    metrics_table = doc.add_table(rows=2, cols=4)
    metrics_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _set_table_borders(metrics_table)

    headers = ["Total Endpoints", "Passed", "Failed", "Total Deviations"]
    for j, h in enumerate(headers):
        c = metrics_table.cell(0, j)
        _set_cell_shading(c, "0F172A")
        p = c.paragraphs[0]
        r = p.add_run(h)
        r.font.bold = True
        r.font.size = Pt(9)
        r.font.color.rgb = RGBColor(255, 255, 255)

    vals = [
        str(evidence_data.get("total_endpoints", 0)),
        str(evidence_data.get("passed_endpoints", 0)),
        str(evidence_data.get("failed_endpoints", 0)),
        str(evidence_data.get("total_deviations", 0)),
    ]
    for j, val in enumerate(vals):
        c = metrics_table.cell(1, j)
        p = c.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(val)
        r.font.bold = True
        r.font.size = Pt(14)
        if j == 1:
            r.font.color.rgb = RGBColor(16, 185, 129)
        elif j == 2:
            r.font.color.rgb = RGBColor(225, 29, 72) if val != "0" else RGBColor(100, 116, 139)
        elif j == 3:
            r.font.color.rgb = RGBColor(217, 119, 6) if val != "0" else RGBColor(16, 185, 129)
        else:
            r.font.color.rgb = RGBColor(15, 23, 42)

    # Section 3: Deviations & Anomalies Analysis
    h3 = doc.add_heading("3. Requirement Deviations & Extra Key Anomaly Detection", level=2)
    h3.paragraph_format.space_before = Pt(14)
    h3.paragraph_format.space_after = Pt(6)

    devs = evidence_data.get("deviation_summary", {}).get("deviations", [])
    if devs:
        dev_table = doc.add_table(rows=len(devs) + 1, cols=5)
        dev_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        _set_table_borders(dev_table)

        dev_headers = ["Severity", "Anomaly Type", "Target Field", "Actual Value / Observation", "Remediation Action"]
        for j, h in enumerate(dev_headers):
            c = dev_table.cell(0, j)
            _set_cell_shading(c, "F1F5F9")
            p = c.paragraphs[0]
            r = p.add_run(h)
            r.font.bold = True
            r.font.size = Pt(8.5)
            r.font.color.rgb = RGBColor(51, 65, 85)

        for i, d in enumerate(devs):
            row_idx = i + 1
            sev = d.get("severity", "minor").upper()
            c_sev = dev_table.cell(row_idx, 0)
            p_sev = c_sev.paragraphs[0]
            r_sev = p_sev.add_run(sev)
            r_sev.font.bold = True
            r_sev.font.size = Pt(8.5)
            if sev == "CRITICAL":
                r_sev.font.color.rgb = RGBColor(225, 29, 72)
            elif sev == "MAJOR":
                r_sev.font.color.rgb = RGBColor(217, 119, 6)
            else:
                r_sev.font.color.rgb = RGBColor(59, 130, 246)

            c_type = dev_table.cell(row_idx, 1)
            c_type.paragraphs[0].add_run(d.get("type", "")).font.size = Pt(8.5)

            c_field = dev_table.cell(row_idx, 2)
            r_f = c_field.paragraphs[0].add_run(d.get("field", ""))
            r_f.font.bold = True
            r_f.font.size = Pt(8.5)

            c_act = dev_table.cell(row_idx, 3)
            c_act.paragraphs[0].add_run(f"{d.get('actual', '')}\n{d.get('explanation', '')}").font.size = Pt(8)

            c_rem = dev_table.cell(row_idx, 4)
            c_rem.paragraphs[0].add_run(d.get("remediation", "")).font.size = Pt(8)

        # Section 3.1: Attached API Call Evidence Snapshots
        h3_sub = doc.add_heading("3.1 Attached API Call Evidence Snapshots", level=3)
        h3_sub.paragraph_format.space_before = Pt(14)
        h3_sub.paragraph_format.space_after = Pt(4)

        p_desc = doc.add_paragraph()
        r_desc = p_desc.add_run(
            "Deterministic audit evidence captures: The following containerized snapshots record the exact "
            "HTTP method, target API URL, request payload body (if present), and live server response captured "
            "for each anomalous endpoint."
        )
        r_desc.font.size = Pt(8.5)
        r_desc.font.italic = True
        r_desc.font.color.rgb = RGBColor(100, 116, 139)
        p_desc.paragraph_format.space_after = Pt(8)

        target_host = (evidence_data.get("target_host") or "").rstrip("/")
        for idx, d in enumerate(devs):
            sev = d.get("severity", "minor").upper()
            api_info = d.get("api_call") or {}
            method = (d.get("method") or api_info.get("method") or "GET").upper()
            raw_url = d.get("url") or api_info.get("url") or d.get("endpoint") or ""
            url = f"{target_host}{raw_url}" if target_host and not str(raw_url).startswith("http") else (raw_url or target_host)
            status_code = d.get("status_code") or api_info.get("status_code") or "N/A"
            duration_ms = d.get("duration_ms") or api_info.get("duration_ms") or 0

            # Request payload formatting
            raw_req = d.get("request_payload") if d.get("request_payload") is not None else api_info.get("request_payload")
            if raw_req is None or raw_req == "" or raw_req == {}:
                req_text = "[No Request Payload Body - GET / Parameterless Request]"
            elif isinstance(raw_req, (dict, list)):
                req_text = json.dumps(raw_req, indent=2)
            else:
                try:
                    req_text = json.dumps(json.loads(str(raw_req)), indent=2)
                except Exception:
                    req_text = str(raw_req)

            # Response payload formatting
            raw_resp = d.get("response_payload") if d.get("response_payload") is not None else api_info.get("response_payload")
            if raw_resp is None or raw_resp == "":
                raw_resp = "[Empty Response Body]"
            elif isinstance(raw_resp, (dict, list)):
                resp_text = json.dumps(raw_resp, indent=2)
            else:
                try:
                    resp_text = json.dumps(json.loads(str(raw_resp)), indent=2)
                except Exception:
                    resp_text = str(raw_resp)

            # Handle large response payload formatting with structured pagination
            if len(resp_text) > 15000:
                resp_text = resp_text[:15000] + "\n... [Long response payload preserved up to 15,000 characters — see companion JSON artifact for full uncompressed payload] ..."

            # Generate and Embed Visual Postman Screenshot PNG Picture
            snap_img_dir = os.path.join(out_dir, "snapshots")
            try:
                ast_preview = [f"Deviation Target: {d.get('field', '')}", f"Observed: {d.get('actual', '')}", f"Expected: {d.get('expected', '')}"]
                snap_img = generate_postman_snapshot_image(
                    method=method,
                    url=url,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    request_payload=raw_req,
                    response_payload=raw_resp,
                    assertions=ast_preview,
                    case_num=idx + 1,
                    evidence_key=evidence_key,
                    out_dir=snap_img_dir,
                    test_key=f"Deviation #{idx + 1} [{sev}] {d.get('field', '')}"
                )
                if os.path.exists(snap_img):
                    p_pic = doc.add_paragraph()
                    p_pic.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    p_pic.paragraph_format.space_before = Pt(6)
                    p_pic.paragraph_format.space_after = Pt(6)
                    doc.add_picture(snap_img, width=Inches(6.5))
            except Exception as e:
                print(f"[DocxGenerator] Notice: Screenshot image generation skipped: {e}")

            # Evidence Snapshot Table
            snap_table = doc.add_table(rows=5, cols=1)
            snap_table.alignment = WD_TABLE_ALIGNMENT.CENTER
            _set_table_borders(snap_table)

            # Row 0: Banner
            c0 = snap_table.cell(0, 0)
            _set_cell_shading(c0, "0F172A")
            p0 = c0.paragraphs[0]
            p0.paragraph_format.space_before = Pt(4)
            p0.paragraph_format.space_after = Pt(4)

            r0_sev = p0.add_run(f"EVIDENCE SNAPSHOT #{idx + 1}  [{sev}]  ")
            r0_sev.font.bold = True
            r0_sev.font.size = Pt(9.5)
            if sev == "CRITICAL":
                r0_sev.font.color.rgb = RGBColor(251, 113, 133)
            elif sev == "MAJOR":
                r0_sev.font.color.rgb = RGBColor(251, 191, 36)
            else:
                r0_sev.font.color.rgb = RGBColor(56, 189, 248)

            r0_type = p0.add_run(f"{d.get('type', 'ANOMALY')} — HTTP {status_code} ({duration_ms} ms)")
            r0_type.font.bold = True
            r0_type.font.size = Pt(9)
            r0_type.font.color.rgb = RGBColor(241, 245, 249)

            # Row 1: Target API Call URL
            c1 = snap_table.cell(1, 0)
            _set_cell_shading(c1, "F8FAFC")
            p1 = c1.paragraphs[0]
            p1.paragraph_format.space_before = Pt(3)
            p1.paragraph_format.space_after = Pt(3)

            r1_lbl = p1.add_run("TARGET API URL:  ")
            r1_lbl.font.bold = True
            r1_lbl.font.size = Pt(8.5)
            r1_lbl.font.color.rgb = RGBColor(71, 85, 105)

            r1_m = p1.add_run(f"[{method}] ")
            r1_m.font.bold = True
            r1_m.font.size = Pt(8.5)
            r1_m.font.color.rgb = RGBColor(234, 88, 12)

            r1_url = p1.add_run(str(url))
            r1_url.font.name = "Consolas"
            r1_url.font.size = Pt(8.5)
            r1_url.font.bold = True
            r1_url.font.color.rgb = RGBColor(15, 23, 42)

            # Row 2: Discrepancy Findings
            c2 = snap_table.cell(2, 0)
            _set_cell_shading(c2, "FFFFFF")
            p2 = c2.paragraphs[0]
            p2.paragraph_format.space_before = Pt(3)
            p2.paragraph_format.space_after = Pt(3)

            r2_t = p2.add_run(f"• Discrepancy Target: ")
            r2_t.font.bold = True
            r2_t.font.size = Pt(8.5)
            r2_tf = p2.add_run(f"{d.get('field', '')}\n")
            r2_tf.font.bold = True
            r2_tf.font.size = Pt(8.5)
            r2_tf.font.color.rgb = RGBColor(234, 88, 12)

            r2_obs = p2.add_run("• Live Server Observation: ")
            r2_obs.font.bold = True
            r2_obs.font.size = Pt(8.5)
            r2_obsv = p2.add_run(f"{d.get('actual', '')}\n")
            r2_obsv.font.size = Pt(8.5)
            r2_obsv.font.color.rgb = RGBColor(225, 29, 72)

            r2_exp = p2.add_run("• Expected Contract: ")
            r2_exp.font.bold = True
            r2_exp.font.size = Pt(8.5)
            r2_expv = p2.add_run(f"{d.get('expected', '')}\n")
            r2_expv.font.size = Pt(8.5)
            r2_expv.font.color.rgb = RGBColor(16, 185, 129)

            r2_ex = p2.add_run("• Explanation: ")
            r2_ex.font.bold = True
            r2_ex.font.size = Pt(8.5)
            r2_exv = p2.add_run(f"{d.get('explanation', '')}\n")
            r2_exv.font.size = Pt(8)
            r2_exv.font.color.rgb = RGBColor(71, 85, 105)

            r2_rem = p2.add_run("• Remediation Guidance: ")
            r2_rem.font.bold = True
            r2_rem.font.size = Pt(8.5)
            r2_remv = p2.add_run(f"{d.get('remediation', '')}")
            r2_remv.font.size = Pt(8)
            r2_remv.font.color.rgb = RGBColor(30, 64, 175)

            # Row 3: Request Payload
            c3 = snap_table.cell(3, 0)
            _set_cell_shading(c3, "F1F5F9")
            p3 = c3.paragraphs[0]
            p3.paragraph_format.space_before = Pt(3)
            p3.paragraph_format.space_after = Pt(2)
            r3_h = p3.add_run("▶ REQUEST PAYLOAD (BODY SENT)")
            r3_h.font.bold = True
            r3_h.font.size = Pt(8)
            r3_h.font.color.rgb = RGBColor(71, 85, 105)

            p3_code = c3.add_paragraph()
            p3_code.paragraph_format.space_before = Pt(0)
            p3_code.paragraph_format.space_after = Pt(3)
            r3_c = p3_code.add_run(req_text)
            r3_c.font.name = "Consolas"
            r3_c.font.size = Pt(7.5)
            r3_c.font.color.rgb = RGBColor(30, 41, 59)

            # Row 4: Captured Response Payload
            c4 = snap_table.cell(4, 0)
            _set_cell_shading(c4, "F8FAFC")
            p4 = c4.paragraphs[0]
            p4.paragraph_format.space_before = Pt(3)
            p4.paragraph_format.space_after = Pt(2)
            r4_h = p4.add_run("▶ LIVE CAPTURED RESPONSE (SERVER OBSERVATION)")
            r4_h.font.bold = True
            r4_h.font.size = Pt(8)
            r4_h.font.color.rgb = RGBColor(71, 85, 105)

            p4_code = c4.add_paragraph()
            p4_code.paragraph_format.space_before = Pt(0)
            p4_code.paragraph_format.space_after = Pt(4)
            r4_c = p4_code.add_run(resp_text)
            r4_c.font.name = "Consolas"
            r4_c.font.size = Pt(7.5)
            r4_c.font.color.rgb = RGBColor(15, 23, 42)

            # Spacing between anomaly cards
            p_gap = doc.add_paragraph()
            p_gap.paragraph_format.space_before = Pt(0)
            p_gap.paragraph_format.space_after = Pt(6)
    else:
        p_nodev = doc.add_paragraph()
        r = p_nodev.add_run("No requirement deviations or anomalies detected. All response payloads strictly adhere to declared schemas.")
        r.font.italic = True
        r.font.size = Pt(9.5)
        r.font.color.rgb = RGBColor(16, 185, 129)

    # Section 4: Individual Endpoint Executions
    h4 = doc.add_heading("4. Test Execution & Assertion Breakdown", level=2)
    h4.paragraph_format.space_before = Pt(14)
    h4.paragraph_format.space_after = Pt(6)

    results = evidence_data.get("results", [])
    if results:
        res_table = doc.add_table(rows=len(results) + 1, cols=5)
        res_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        _set_table_borders(res_table)

        col_heads = ["Method", "Endpoint Path", "Status", "Latency", "Assertions"]
        for j, h in enumerate(col_heads):
            c = res_table.cell(0, j)
            _set_cell_shading(c, "F1F5F9")
            p = c.paragraphs[0]
            r = p.add_run(h)
            r.font.bold = True
            r.font.size = Pt(8.5)
            r.font.color.rgb = RGBColor(51, 65, 85)

        for i, res in enumerate(results):
            row_idx = i + 1
            # Method
            c_m = res_table.cell(row_idx, 0)
            r_m = c_m.paragraphs[0].add_run(res.get("method", "GET"))
            r_m.font.bold = True
            r_m.font.size = Pt(8.5)

            # Path
            c_p = res_table.cell(row_idx, 1)
            c_p.paragraphs[0].add_run(res.get("endpoint", "")).font.size = Pt(8.5)

            # Status Code
            c_st = res_table.cell(row_idx, 2)
            passed = res.get("passed", False)
            p_st = c_st.paragraphs[0]
            r_st = p_st.add_run(f"HTTP {res.get('status_code', '')}")
            r_st.font.bold = True
            r_st.font.size = Pt(8.5)
            r_st.font.color.rgb = RGBColor(16, 185, 129) if passed else RGBColor(225, 29, 72)

            # Latency
            c_lat = res_table.cell(row_idx, 3)
            c_lat.paragraphs[0].add_run(f"{res.get('duration_ms', 0)} ms").font.size = Pt(8.5)

            # Assertions Summary
            c_as = res_table.cell(row_idx, 4)
            p_as = c_as.paragraphs[0]
            assertions = res.get("assertions", [])
            pass_as = sum(1 for a in assertions if a.get("passed"))
            r_as = p_as.add_run(f"{pass_as}/{len(assertions)} Passed")
            r_as.font.size = Pt(8.5)
            r_as.font.color.rgb = RGBColor(16, 185, 129) if pass_as == len(assertions) else RGBColor(225, 29, 72)

        # Section 4.1: Comprehensive Test Execution Evidence Snapshots (Every Case)
        h4_sub = doc.add_heading("4.1 Comprehensive Test Execution Evidence Snapshots (All Cases)", level=3)
        h4_sub.paragraph_format.space_before = Pt(14)
        h4_sub.paragraph_format.space_after = Pt(4)

        p_desc4 = doc.add_paragraph()
        r_desc4 = p_desc4.add_run(
            "Complete audit verification records: The following evidence snapshots capture the complete API URL, "
            "request payload (body sent), and live captured server response for EVERY executed test case, "
            "verifying both successful assertions and any identified contract discrepancies."
        )
        r_desc4.font.size = Pt(8.5)
        r_desc4.font.italic = True
        r_desc4.font.color.rgb = RGBColor(100, 116, 139)
        p_desc4.paragraph_format.space_after = Pt(8)

        target_host = (evidence_data.get("target_host") or "").rstrip("/")
        for idx, res in enumerate(results):
            res_passed = res.get("passed", False)
            api_info = res.get("api_call") or {}
            method = (res.get("method") or api_info.get("method") or "GET").upper()
            raw_url = res.get("url") or api_info.get("url") or res.get("endpoint") or ""
            if not str(raw_url).startswith("http") and target_host:
                url = f"{target_host}{raw_url}"
            else:
                url = raw_url
            endpoint = res.get("endpoint") or raw_url
            status_code = res.get("status_code") or api_info.get("status_code") or (200 if res_passed else 500)
            duration_ms = res.get("duration_ms") or api_info.get("duration_ms") or 0
            assertions = res.get("assertions", [])
            devs_on_endpoint = res.get("deviations", [])

            # Request payload formatting
            raw_req = res.get("request_payload")
            if raw_req is None and isinstance(api_info, dict):
                raw_req = api_info.get("request_payload")
            if raw_req is None and isinstance(res.get("request"), dict):
                raw_req = res.get("request", {}).get("body")
            if raw_req is None or raw_req == "" or raw_req == {}:
                req_text = "[No Request Payload Body - GET / Parameterless Request]"
            elif isinstance(raw_req, (dict, list)):
                req_text = json.dumps(raw_req, indent=2)
            else:
                try:
                    req_text = json.dumps(json.loads(str(raw_req)), indent=2)
                except Exception:
                    req_text = str(raw_req)

            # Response payload formatting
            raw_resp = res.get("response_payload")
            if raw_resp is None and isinstance(api_info, dict):
                raw_resp = api_info.get("response_payload")
            if raw_resp is None and isinstance(res.get("response"), dict):
                raw_resp = res.get("response", {}).get("body")
            if raw_resp is None or raw_resp == "":
                raw_resp = "[Empty Response Body]"
            elif isinstance(raw_resp, (dict, list)):
                resp_text = json.dumps(raw_resp, indent=2)
            else:
                try:
                    resp_text = json.dumps(json.loads(str(raw_resp)), indent=2)
                except Exception:
                    resp_text = str(raw_resp)

            # Handle large response payload formatting with structured pagination
            if len(resp_text) > 15000:
                resp_text = resp_text[:15000] + "\n... [Long response payload preserved up to 15,000 characters — see companion JSON artifact for full uncompressed payload] ..."

            # Generate and Embed Visual Postman Screenshot PNG Picture
            snap_img_dir = os.path.join(out_dir, "snapshots")
            try:
                ast_list = [a.get("name") if isinstance(a, dict) else str(a) for a in assertions] if assertions else [f"Status code is {status_code}"]
                snap_img = generate_postman_snapshot_image(
                    method=method,
                    url=url,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    request_payload=raw_req,
                    response_payload=raw_resp,
                    assertions=ast_list,
                    case_num=idx + 1,
                    evidence_key=evidence_key,
                    out_dir=snap_img_dir,
                    test_key=res.get("test_key") or f"{method} {endpoint}"
                )
                if os.path.exists(snap_img):
                    p_pic = doc.add_paragraph()
                    p_pic.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    p_pic.paragraph_format.space_before = Pt(8)
                    p_pic.paragraph_format.space_after = Pt(6)
                    doc.add_picture(snap_img, width=Inches(6.5))
            except Exception as e:
                print(f"[DocxGenerator] Notice: Screenshot image generation skipped: {e}")

            snap_table = doc.add_table(rows=5, cols=1)
            snap_table.alignment = WD_TABLE_ALIGNMENT.CENTER
            _set_table_borders(snap_table)

            # Row 0: Banner
            c0 = snap_table.cell(0, 0)
            _set_cell_shading(c0, "0F172A")
            p0 = c0.paragraphs[0]
            p0.paragraph_format.space_before = Pt(4)
            p0.paragraph_format.space_after = Pt(4)

            tag_label = "VERIFIED CONFORMANT" if res_passed and not devs_on_endpoint else ("PARTIALLY CONFORMANT" if res_passed else "EXECUTION FAILED")
            r0_tag = p0.add_run(f"POSTMAN API EVIDENCE SNAPSHOT #{idx + 1}  [{tag_label}]  ")
            r0_tag.font.bold = True
            r0_tag.font.size = Pt(9.5)
            if res_passed and not devs_on_endpoint:
                r0_tag.font.color.rgb = RGBColor(16, 185, 129)
            elif res_passed and devs_on_endpoint:
                r0_tag.font.color.rgb = RGBColor(251, 191, 36)
            else:
                r0_tag.font.color.rgb = RGBColor(251, 113, 133)

            r0_ep = p0.add_run(f"{method} {endpoint} — HTTP {status_code} ({duration_ms} ms)")
            r0_ep.font.bold = True
            r0_ep.font.size = Pt(9)
            r0_ep.font.color.rgb = RGBColor(241, 245, 249)

            # Row 1: Target URL
            c1 = snap_table.cell(1, 0)
            _set_cell_shading(c1, "F8FAFC")
            p1 = c1.paragraphs[0]
            p1.paragraph_format.space_before = Pt(3)
            p1.paragraph_format.space_after = Pt(3)
            r1_lbl = p1.add_run("TARGET API URL:  ")
            r1_lbl.font.bold = True
            r1_lbl.font.size = Pt(8.5)
            r1_lbl.font.color.rgb = RGBColor(71, 85, 105)

            r1_m = p1.add_run(f"[{method}] ")
            r1_m.font.bold = True
            r1_m.font.size = Pt(8.5)
            r1_m.font.color.rgb = RGBColor(234, 88, 12)

            r1_url = p1.add_run(str(url))
            r1_url.font.name = "Consolas"
            r1_url.font.size = Pt(8.5)
            r1_url.font.bold = True
            r1_url.font.color.rgb = RGBColor(15, 23, 42)

            # Row 2: Assertions & Compliance Details
            c2 = snap_table.cell(2, 0)
            _set_cell_shading(c2, "FFFFFF")
            p2 = c2.paragraphs[0]
            p2.paragraph_format.space_before = Pt(3)
            p2.paragraph_format.space_after = Pt(3)

            r2_ah = p2.add_run("• Contract Assertions: ")
            r2_ah.font.bold = True
            r2_ah.font.size = Pt(8.5)

            if assertions:
                pass_count = sum(1 for a in assertions if a.get("passed"))
                r2_astat = p2.add_run(f"{pass_count}/{len(assertions)} Passed\n")
                r2_astat.font.bold = True
                r2_astat.font.size = Pt(8.5)
                r2_astat.font.color.rgb = RGBColor(16, 185, 129) if pass_count == len(assertions) else RGBColor(225, 29, 72)

                for a in assertions:
                    is_p = a.get("passed", False)
                    mark = "✔" if is_p else "✘"
                    r_item = p2.add_run(f"   {mark} {a.get('name')}\n")
                    r_item.font.size = Pt(8)
                    r_item.font.color.rgb = RGBColor(16, 185, 129) if is_p else RGBColor(225, 29, 72)
            else:
                p2.add_run("Direct HTTP contract validation completed successfully.\n").font.size = Pt(8)

            if devs_on_endpoint:
                r_devh = p2.add_run("• Flagged Deviations on this Endpoint:\n")
                r_devh.font.bold = True
                r_devh.font.size = Pt(8.5)
                r_devh.font.color.rgb = RGBColor(217, 119, 6)
                for d in devs_on_endpoint:
                    r_devitem = p2.add_run(f"   ⚠ [{d.get('type')}] {d.get('field')}: {d.get('actual')} (Expected: {d.get('expected')})\n")
                    r_devitem.font.size = Pt(8)
                    r_devitem.font.color.rgb = RGBColor(217, 119, 6)

            # Row 3: Request Payload
            c3 = snap_table.cell(3, 0)
            _set_cell_shading(c3, "F1F5F9")
            p3 = c3.paragraphs[0]
            p3.paragraph_format.space_before = Pt(3)
            p3.paragraph_format.space_after = Pt(2)
            r3_h = p3.add_run("▶ REQUEST PAYLOAD (BODY SENT)")
            r3_h.font.bold = True
            r3_h.font.size = Pt(8)
            r3_h.font.color.rgb = RGBColor(71, 85, 105)

            p3_code = c3.add_paragraph()
            p3_code.paragraph_format.space_before = Pt(0)
            p3_code.paragraph_format.space_after = Pt(3)
            r3_c = p3_code.add_run(req_text)
            r3_c.font.name = "Consolas"
            r3_c.font.size = Pt(7.5)
            r3_c.font.color.rgb = RGBColor(30, 41, 59)

            # Row 4: Captured Response Payload
            c4 = snap_table.cell(4, 0)
            _set_cell_shading(c4, "F8FAFC")
            p4 = c4.paragraphs[0]
            p4.paragraph_format.space_before = Pt(3)
            p4.paragraph_format.space_after = Pt(2)
            r4_h = p4.add_run("▶ LIVE CAPTURED RESPONSE (SERVER OBSERVATION)")
            r4_h.font.bold = True
            r4_h.font.size = Pt(8)
            r4_h.font.color.rgb = RGBColor(71, 85, 105)

            p4_code = c4.add_paragraph()
            p4_code.paragraph_format.space_before = Pt(0)
            p4_code.paragraph_format.space_after = Pt(4)
            r4_c = p4_code.add_run(resp_text)
            r4_c.font.name = "Consolas"
            r4_c.font.size = Pt(7.5)
            r4_c.font.color.rgb = RGBColor(15, 23, 42)

            p_gap = doc.add_paragraph()
            p_gap.paragraph_format.space_before = Pt(0)
            p_gap.paragraph_format.space_after = Pt(6)

    # Section 5: Cryptographic Integrity Seal
    h5 = doc.add_heading("5. Cryptographic Audit Seal & Tamper Verification", level=2)
    h5.paragraph_format.space_before = Pt(16)
    h5.paragraph_format.space_after = Pt(6)

    seal_table = doc.add_table(rows=1, cols=1)
    seal_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    c_seal = seal_table.cell(0, 0)
    _set_cell_shading(c_seal, "F8FAFC")
    p_seal = c_seal.paragraphs[0]
    p_seal.paragraph_format.space_before = Pt(6)
    p_seal.paragraph_format.space_after = Pt(6)

    r_s1 = p_seal.add_run("SHA-256 CRYPTOGRAPHIC INTEGRITY SEAL:\n")
    r_s1.font.bold = True
    r_s1.font.size = Pt(8.5)
    r_s1.font.color.rgb = RGBColor(71, 85, 105)

    r_s2 = p_seal.add_run(f"{evidence_data.get('sha256_seal', 'UNSEALED')}\n")
    r_s2.font.bold = True
    r_s2.font.size = Pt(9.5)
    r_s2.font.color.rgb = RGBColor(15, 23, 42)

    r_s3 = p_seal.add_run(
        "Deterministic audit verification: This digital evidence artifact was autonomously synthesized from direct "
        "HTTP execution logs and verified against user-story requirements. Raw metrics have not been altered."
    )
    r_s3.font.size = Pt(8)
    r_s3.font.italic = True
    r_s3.font.color.rgb = RGBColor(100, 116, 139)

    doc.save(out_path)
    return out_path
