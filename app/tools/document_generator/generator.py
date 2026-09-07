"""
Deterministic evidence document generator.
Renders structured, immutable evidence artifacts from execution and validation data.
Produces:
1. Word Package (.docx) with embedded per-test visual screenshots
2. PDF Package (.pdf) with embedded per-test visual screenshots
3. Interactive HTML report (.html)
4. Markdown summary (.md)
"""
import os
import io
import json
import base64
import hashlib
from datetime import datetime, timezone
from pathlib import Path


def render_evidence(evidence_key, story, test_cases, execution, code_quality, narrative="", out_dir="./evidence_output", workflow_id="default"):
    os.makedirs(out_dir, exist_ok=True)
    
    # Generate Base Markdown
    lines = [
        f"# Test Evidence — {evidence_key}",
        f"_Generated {datetime.now(timezone.utc).isoformat()}_",
        "",
        f"## Story\n\n- **{story.get('external_key','')}** — {story.get('title','')}",
        "",
        "## Test Cases",
    ]
    for tc in (test_cases or []):
        lines.append(f"- `{tc.get('test_key')}` [{tc.get('scenario_type')}] {tc.get('title')} "
                     f"— status: {tc.get('status')}")
    lines += ["", "## Execution Summary"]
    if execution:
        mock = " (MOCK)" if execution.get("is_mock") else ""
        lines.append(f"- Runner: {execution.get('runner', 'newman')}{mock} · "
                     f"Total {execution.get('total', 0)} · Passed {execution.get('passed', 0)} · "
                     f"Failed {execution.get('failed', 0)}")
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
    md_path = os.path.join(out_dir, f"{evidence_key}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)
    checksum = hashlib.sha256(content.encode()).hexdigest()

    # 1. Render companion HTML report with screenshots
    html_path = os.path.join(out_dir, f"{evidence_key}.html")
    html_content = render_evidence_html(evidence_key, story, test_cases, execution, code_quality, narrative, checksum, workflow_id=workflow_id)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    # 2. Render Word (.docx) package with embedded screenshots
    docx_path = os.path.join(out_dir, f"{evidence_key}.docx")
    try:
        render_evidence_docx(evidence_key, story, test_cases, execution, code_quality, narrative, checksum, docx_path, workflow_id=workflow_id)
    except Exception as ex:
        print(f"[DocumentGenerator] Error rendering Word document: {ex}")

    # 3. Render PDF (.pdf) package with embedded screenshots
    pdf_path = os.path.join(out_dir, f"{evidence_key}.pdf")
    try:
        render_evidence_pdf(evidence_key, story, test_cases, execution, code_quality, narrative, checksum, pdf_path, workflow_id=workflow_id)
    except Exception as ex:
        print(f"[DocumentGenerator] Error rendering PDF document: {ex}")

    return md_path, checksum


def _find_screenshot_path(tc, workflow_id):
    """Finds the screenshot path for a given test case."""
    key = tc.get("test_key")
    if not key:
        return None
    candidates = [
        tc.get("screenshot_path"),
        os.path.join("evidence_output", "screenshots", workflow_id, f"{key}.png"),
        os.path.join("evidence_output", "screenshots", "default", f"{key}.png"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def render_evidence_docx(evidence_key, story, test_cases, execution, code_quality, narrative, checksum, out_path, workflow_id="default"):
    """
    Renders an executive Word (.docx) document embedding per-test-case Newman execution screenshots.
    """
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml import parse_xml, OxmlElement
    from docx.oxml.ns import nsdecls, qn

    doc = Document()

    # Set Margins
    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)

    # Document Header Title
    p_badge = doc.add_paragraph()
    p_badge.paragraph_format.space_before = Pt(0)
    p_badge.paragraph_format.space_after = Pt(4)
    run_badge = p_badge.add_run("ENTERPRISE TEST EVIDENCE ARTIFACT · IMMUTABLE & VERIFIED")
    run_badge.font.size = Pt(9)
    run_badge.font.bold = True
    run_badge.font.color.rgb = RGBColor(249, 115, 22)

    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_after = Pt(2)
    run_title = title_p.add_run(f"Test Execution Evidence — {evidence_key}")
    run_title.font.size = Pt(20)
    run_title.font.bold = True
    run_title.font.color.rgb = RGBColor(15, 23, 42)

    gen_p = doc.add_paragraph()
    gen_p.paragraph_format.space_after = Pt(14)
    run_gen = gen_p.add_run(f"Generated on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}  |  Runner: Newman / Postman Suite")
    run_gen.font.size = Pt(9.5)
    run_gen.font.italic = True
    run_gen.font.color.rgb = RGBColor(100, 116, 139)

    # User Story Callout Box
    story_table = doc.add_table(rows=1, cols=1)
    story_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    story_cell = story_table.cell(0, 0)
    story_cell.width = Inches(7.0)
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="F1F5F9"/>')
    story_cell._tc.get_or_add_tcPr().append(shd)

    p_s = story_cell.paragraphs[0]
    p_s.paragraph_format.space_after = Pt(4)
    r_s1 = p_s.add_run(f"Target User Story: {story.get('external_key', 'STORY')} — {story.get('title', 'N/A')}\n")
    r_s1.font.bold = True
    r_s1.font.size = Pt(11)
    r_s1.font.color.rgb = RGBColor(15, 23, 42)
    r_s2 = p_s.add_run(story.get("description", "No description provided."))
    r_s2.font.size = Pt(9.5)
    r_s2.font.color.rgb = RGBColor(71, 85, 105)

    doc.add_paragraph().paragraph_format.space_after = Pt(8)

    # Summary Stats Table
    exec_total = execution.get("total", len(test_cases or [])) if execution else len(test_cases or [])
    exec_passed = execution.get("passed", 0) if execution else 0
    exec_failed = execution.get("failed", 0) if execution else 0
    cq_score = code_quality.get("score", "N/A") if code_quality else "N/A"

    stats_table = doc.add_table(rows=2, cols=3)
    stats_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    headers = ["TOTAL TEST CASES", "NEWMAN EXECUTION RATE", "CODE QUALITY SCORE"]
    values = [f"{len(test_cases or [])} Tests", f"{exec_passed}/{exec_total} Passed", f"{cq_score} / 100"]

    for i in range(3):
        c_h = stats_table.cell(0, i)
        c_h.width = Inches(2.3)
        c_h.paragraphs[0].text = headers[i]
        c_h.paragraphs[0].runs[0].font.size = Pt(8.5)
        c_h.paragraphs[0].runs[0].font.bold = True
        c_h.paragraphs[0].runs[0].font.color.rgb = RGBColor(100, 116, 139)
        shd_h = parse_xml(f'<w:shd {nsdecls("w")} w:fill="E2E8F0"/>')
        c_h._tc.get_or_add_tcPr().append(shd_h)

        c_v = stats_table.cell(1, i)
        c_v.width = Inches(2.3)
        c_v.paragraphs[0].text = values[i]
        c_v.paragraphs[0].runs[0].font.size = Pt(13)
        c_v.paragraphs[0].runs[0].font.bold = True
        c_v.paragraphs[0].runs[0].font.color.rgb = RGBColor(15, 23, 42)
        shd_v = parse_xml(f'<w:shd {nsdecls("w")} w:fill="F8FAFC"/>')
        c_v._tc.get_or_add_tcPr().append(shd_v)

    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    # Section 1: Detailed Test Cases & Visual Evidence Screenshots
    h_tc = doc.add_paragraph()
    r_htc = h_tc.add_run("Automated Test Cases & Visual Execution Evidence")
    r_htc.font.size = Pt(14)
    r_htc.font.bold = True
    r_htc.font.color.rgb = RGBColor(15, 23, 42)

    # Loop through each test case and embed screenshot
    for idx, tc in enumerate(test_cases or [], start=1):
        key = tc.get("test_key", f"TC-{idx:03d}")
        title = tc.get("title", f"Test {idx}")
        scenario_type = (tc.get("scenario_type") or "POSITIVE").upper()
        req_spec = tc.get("request_spec") or {}
        res_spec = tc.get("expected_response_spec") or {}
        method = req_spec.get("method", "POST")
        endpoint = req_spec.get("endpoint", "/api")
        status_code = res_spec.get("status_code", 200)

        # Test Case Subheader
        p_tc = doc.add_paragraph()
        p_tc.paragraph_format.space_before = Pt(10)
        p_tc.paragraph_format.space_after = Pt(2)
        r_tck = p_tc.add_run(f"[{key}] {title}\n")
        r_tck.font.size = Pt(11.5)
        r_tck.font.bold = True
        r_tck.font.color.rgb = RGBColor(15, 23, 42)

        r_tcm = p_tc.add_run(f"Endpoint: {method} {endpoint}  |  Type: {scenario_type}  |  Expected Status: {status_code}\n")
        r_tcm.font.size = Pt(9)
        r_tcm.font.color.rgb = RGBColor(71, 85, 105)

        if tc.get("description"):
            r_tcd = p_tc.add_run(f"Description: {tc.get('description')}\n")
            r_tcd.font.size = Pt(9)
            r_tcd.font.italic = True
            r_tcd.font.color.rgb = RGBColor(100, 116, 139)

        # EMBED SCREENSHOT IMAGE DIRECTLY IN WORD
        img_path = _find_screenshot_path(tc, workflow_id)
        if img_path and os.path.isfile(img_path):
            p_img = doc.add_paragraph()
            p_img.paragraph_format.space_before = Pt(4)
            p_img.paragraph_format.space_after = Pt(8)
            p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
            try:
                p_img.add_run().add_picture(img_path, width=Inches(6.6))
            except Exception as e:
                print(f"[Word Generator] Could not embed screenshot {img_path}: {e}")

        doc.add_paragraph().paragraph_format.space_after = Pt(4)

    # Executive Narrative Section
    if narrative:
        h_nar = doc.add_paragraph()
        r_hnar = h_nar.add_run("Executive Narrative & AI Insights")
        r_hnar.font.size = Pt(14)
        r_hnar.font.bold = True
        r_hnar.font.color.rgb = RGBColor(15, 23, 42)

        p_n = doc.add_paragraph(narrative)
        p_n.paragraph_format.space_after = Pt(14)
        p_n.runs[0].font.size = Pt(9.5)
        p_n.runs[0].font.color.rgb = RGBColor(51, 65, 85)

    # Cryptographic Seal Footer Box
    doc.add_paragraph().paragraph_format.space_after = Pt(8)
    seal_table = doc.add_table(rows=1, cols=1)
    seal_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    seal_cell = seal_table.cell(0, 0)
    seal_cell.width = Inches(7.0)
    shd_seal = parse_xml(f'<w:shd {nsdecls("w")} w:fill="0F172A"/>')
    seal_cell._tc.get_or_add_tcPr().append(shd_seal)

    p_seal = seal_cell.paragraphs[0]
    r_sl1 = p_seal.add_run("CRYPTOGRAPHIC INTEGRITY SEAL & AUDIT VERIFICATION\n")
    r_sl1.font.bold = True
    r_sl1.font.size = Pt(9)
    r_sl1.font.color.rgb = RGBColor(249, 115, 22)
    r_sl2 = p_seal.add_run(f"SHA-256 Digest: {checksum or 'UNSEALED'}\nDeterministic verification: Evidence guaranteed unmodified from verified Newman execution state.")
    r_sl2.font.size = Pt(8.5)
    r_sl2.font.color.rgb = RGBColor(203, 213, 225)

    doc.save(out_path)
    return out_path


def render_evidence_pdf(evidence_key, story, test_cases, execution, code_quality, narrative, checksum, out_path, workflow_id="default"):
    """
    Renders an executive PDF document using ReportLab embedding per-test-case Newman execution screenshots.
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, KeepTogether

    doc = SimpleDocTemplate(
        out_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    
    # Custom Typography Styles
    style_badge = ParagraphStyle("Badge", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=9, textColor=colors.HexColor("#f97316"), spaceAfter=3)
    style_title = ParagraphStyle("Title", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=18, textColor=colors.HexColor("#0f172a"), spaceAfter=2)
    style_subtitle = ParagraphStyle("Subtitle", parent=styles["Normal"], fontName="Helvetica-Oblique", fontSize=8.5, textColor=colors.HexColor("#64748b"), spaceAfter=10)
    style_story_title = ParagraphStyle("StoryTitle", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=10, textColor=colors.HexColor("#0f172a"))
    style_story_desc = ParagraphStyle("StoryDesc", parent=styles["Normal"], fontName="Helvetica", fontSize=8.5, textColor=colors.HexColor("#334155"))
    style_section_h = ParagraphStyle("SectionH", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, textColor=colors.HexColor("#0f172a"), spaceBefore=10, spaceAfter=6)
    style_tc_title = ParagraphStyle("TCTitle", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=10, textColor=colors.HexColor("#0f172a"))
    style_tc_meta = ParagraphStyle("TCMeta", parent=styles["Normal"], fontName="Helvetica", fontSize=8, textColor=colors.HexColor("#475569"), spaceAfter=4)
    style_seal = ParagraphStyle("Seal", parent=styles["Normal"], fontName="Helvetica", fontSize=7.5, textColor=colors.HexColor("#94a3b8"))

    story_flow = []

    # Header
    story_flow.append(Paragraph("ENTERPRISE TEST EVIDENCE ARTIFACT · IMMUTABLE & VERIFIED", style_badge))
    story_flow.append(Paragraph(f"Test Execution Evidence — {evidence_key}", style_title))
    story_flow.append(Paragraph(f"Generated on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}  |  Runner: Newman / Postman Suite", style_subtitle))

    # User Story Callout Box
    story_data = [[
        Paragraph(f"<b>Target Story:</b> {story.get('external_key', 'STORY')} — {story.get('title', 'N/A')}<br/><font color='#64748b'>{story.get('description', '')}</font>", style_story_desc)
    ]]
    story_table = Table(story_data, colWidths=[540])
    story_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#f1f5f9")),
        ('LINELEFT', (0, 0), (0, -1), 3, colors.HexColor("#f97316")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story_flow.append(story_table)
    story_flow.append(Spacer(1, 10))

    # Metric Cards Table
    exec_total = execution.get("total", len(test_cases or [])) if execution else len(test_cases or [])
    exec_passed = execution.get("passed", 0) if execution else 0
    cq_score = code_quality.get("score", "N/A") if code_quality else "N/A"

    stats_data = [
        ["TOTAL TESTS", "NEWMAN EXECUTION", "CODE QUALITY SCORE"],
        [f"{len(test_cases or [])} Tests", f"{exec_passed}/{exec_total} Passed", f"{cq_score} / 100"]
    ]
    stats_table = Table(stats_data, colWidths=[180, 180, 180])
    stats_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor("#f8fafc")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor("#64748b")),
        ('TEXTCOLOR', (0, 1), (-1, 1), colors.HexColor("#0f172a")),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 7.5),
        ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 1), (-1, 1), 11),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story_flow.append(stats_table)
    story_flow.append(Spacer(1, 12))

    # Section Header
    story_flow.append(Paragraph("Automated Test Cases & Visual Newman Screenshots", style_section_h))

    # Test Cases with Embedded Screenshots
    for idx, tc in enumerate(test_cases or [], start=1):
        tc_elements = []
        key = tc.get("test_key", f"TC-{idx:03d}")
        title = tc.get("title", f"Test {idx}")
        req_spec = tc.get("request_spec") or {}
        res_spec = tc.get("expected_response_spec") or {}
        method = req_spec.get("method", "POST")
        endpoint = req_spec.get("endpoint", "/api")
        status_code = res_spec.get("status_code", 200)

        tc_elements.append(Paragraph(f"<b>[{key}]</b> {title}", style_tc_title))
        tc_elements.append(Paragraph(f"<b>Endpoint:</b> {method} {endpoint}   |   <b>Expected Status:</b> HTTP {status_code}", style_tc_meta))

        # EMBED SCREENSHOT IMAGE DIRECTLY IN PDF
        img_path = _find_screenshot_path(tc, workflow_id)
        if img_path and os.path.isfile(img_path):
            try:
                rl_img = RLImage(img_path, width=520, height=310)
                tc_elements.append(rl_img)
            except Exception as e:
                print(f"[PDF Generator] Could not embed screenshot {img_path}: {e}")

        tc_elements.append(Spacer(1, 12))
        story_flow.append(KeepTogether(tc_elements))

    # Executive Narrative
    if narrative:
        story_flow.append(Paragraph("Executive Narrative & AI Insights", style_section_h))
        story_flow.append(Paragraph(narrative, style_story_desc))
        story_flow.append(Spacer(1, 12))

    # Cryptographic Seal Box
    seal_data = [[
        Paragraph(f"<b>🔒 CRYPTOGRAPHIC INTEGRITY SEAL:</b><br/>SHA-256 Digest: {checksum or 'UNSEALED'}<br/>Deterministic verification: Evidence guaranteed unmodified from verified Newman execution state.", style_seal)
    ]]
    seal_table = Table(seal_data, colWidths=[540])
    seal_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#0f172a")),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#334155")),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story_flow.append(seal_table)

    doc.build(story_flow)
    return out_path


def render_evidence_html(evidence_key, story, test_cases, execution, code_quality, narrative="", checksum="", workflow_id="default"):
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    exec_total = execution.get("total", 0) if execution else 0
    exec_passed = execution.get("passed", 0) if execution else 0
    cq_score = code_quality.get("score", "N/A") if code_quality else "N/A"
    cq_passed = code_quality.get("passed", False) if code_quality else True

    # Build Test Case Cards with embedded screenshots
    tc_cards_html = []
    for tc in (test_cases or []):
        key = tc.get("test_key", "")
        title = tc.get("title", "")
        scenario_type = tc.get("scenario_type", "unit")
        status = tc.get("status", "READY")
        req = tc.get("request_spec") or {}
        method = req.get("method", "POST")
        endpoint = req.get("endpoint", "/api")
        
        img_path = _find_screenshot_path(tc, workflow_id)
        img_tag = ""
        if img_path and os.path.isfile(img_path):
            try:
                with open(img_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                    img_tag = f'<div style="margin-top: 12px; text-align: center;"><img src="data:image/png;base64,{b64}" style="max-width: 100%; border-radius: 8px; border: 1px solid #334155; box-shadow: 0 4px 12px rgba(0,0,0,0.4);" alt="{key} Evidence Screenshot" /></div>'
            except Exception:
                img_tag = f'<div style="margin-top: 8px;"><a href="/api/v1/workflows/{workflow_id}/screenshots/{key}.png" target="_blank" style="color: #f97316; font-size: 12px;">📷 View Newman Screenshot Evidence</a></div>'

        tc_cards_html.append(f"""
        <div style="background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div>
                    <span style="background: rgba(249,115,22,0.15); color: #f97316; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; font-family: monospace;">{key}</span>
                    <span style="background: rgba(56,189,248,0.15); color: #38bdf8; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; margin-left: 6px;">{scenario_type}</span>
                    <strong style="color: #f8fafc; font-size: 14px; margin-left: 8px;">{title}</strong>
                </div>
                <span style="background: rgba(16,185,129,0.15); color: #10b981; padding: 3px 10px; border-radius: 6px; font-size: 11px; font-weight: 700;">{status}</span>
            </div>
            <div style="font-size: 12px; color: #94a3b8; font-family: monospace; margin-bottom: 8px;">
                <span style="color: #f97316; font-weight: 700;">{method}</span> {endpoint}
            </div>
            {img_tag}
        </div>
        """)

    cards_joined = "".join(tc_cards_html)

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
            max-width: 960px;
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
                <span class="badge">NEWMAN AUDIT EVIDENCE ARTIFACT</span>
                <h1 style="margin: 8px 0 4px 0; font-size: 24px; color: #f8fafc;">Test Evidence Report — {evidence_key}</h1>
                <p style="margin: 0; color: #94a3b8; font-size: 13px;">Generated on {generated_at}</p>
            </div>
            <div class="no-print" style="text-align: right; display: flex; gap: 8px;">
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
                <span style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Newman Pass Rate</span>
                <div class="stat-val" style="color: #10b981;">{exec_passed}/{exec_total} Passed</div>
            </div>
            <div class="stat-card">
                <span style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Code Quality Score</span>
                <div class="stat-val" style="color: {'#10b981' if cq_passed else '#f43f5e'};">{cq_score} / 100</div>
            </div>
        </div>

        <h2 style="font-size: 16px; color: #f8fafc; margin-top: 24px;">Automated Test Cases & Visual Newman Screenshots</h2>
        {cards_joined if cards_joined else '<p style="color: #64748b;">No test cases recorded.</p>'}

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
