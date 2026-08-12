"""
Deterministic evidence document generator. Renders a structured evidence file from
persisted execution/validation data. Never mutates the underlying results. Produces a
Markdown/HTML artifact by default (dependency-free); DOCX/PDF adapters can be added.
"""
import os
import hashlib
from datetime import datetime, timezone


def render_evidence(evidence_key, story, test_cases, execution, code_quality, out_dir="./evidence_output"):
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

    content = "\n".join(lines)
    path = os.path.join(out_dir, f"{evidence_key}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    checksum = hashlib.sha256(content.encode()).hexdigest()
    return path, checksum
