from __future__ import annotations

import html
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from fpdf import FPDF

from assure_contracts.enums import Verdict
from assure_contracts.manifest import RunManifest
from assure_contracts.result import RunSummary


def write_reports(output_dir: Path, summary: RunSummary, manifest: RunManifest) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        summary.model_dump_json(by_alias=True, indent=2),
        encoding="utf-8",
    )
    (output_dir / "manifest.json").write_text(
        manifest.model_dump_json(by_alias=True, indent=2),
        encoding="utf-8",
    )
    (output_dir / "report.html").write_text(html_report(summary), encoding="utf-8")
    (output_dir / "report.junit.xml").write_text(junit_report(summary), encoding="utf-8")
    (output_dir / "report.pdf").write_bytes(pdf_report(summary))


def html_report(summary: RunSummary) -> str:
    return _html(summary)


def junit_report(summary: RunSummary) -> str:
    failures = sum(1 for case in summary.cases if case.verdict == Verdict.FAIL)
    errors = sum(1 for case in summary.cases if case.verdict in {Verdict.INCONCLUSIVE, Verdict.ERROR})
    skipped = sum(1 for case in summary.cases if case.verdict == Verdict.SKIPPED)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<testsuite name="assure" tests="{len(summary.cases)}" '
            f'failures="{failures}" errors="{errors}" skipped="{skipped}">'
        ),
    ]
    for case in summary.cases:
        name = xml_escape(case.case_id)
        counts = xml_escape(f"{case.failed_attempts}/{case.valid_attempts}")
        parts.append(f'  <testcase classname="assure" name="{name}">')
        if case.verdict == Verdict.FAIL:
            parts.append(f'    <failure message="{xml_escape(case.verdict)}">{counts}</failure>')
        elif case.verdict in {Verdict.INCONCLUSIVE, Verdict.ERROR}:
            parts.append(f'    <error message="{xml_escape(case.verdict)}">{counts}</error>')
        elif case.verdict == Verdict.SKIPPED:
            parts.append(f'    <skipped message="{xml_escape(case.verdict)}">{counts}</skipped>')
        parts.append("  </testcase>")
    parts.append("</testsuite>")
    return "\n".join(parts) + "\n"


def pdf_report(summary: RunSummary) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    _pdf_line(pdf, "Assure local report", size=16, bold=True)
    _pdf_line(
        pdf,
        "This report lists tested controls, verdicts, and coverage limits. "
        "It is not a security score and does not certify the application.",
        size=11,
    )
    _pdf_line(
        pdf,
        f"Run: {summary.run_id}\n"
        f"Build: {summary.target_build}\n"
        f"Gate: {summary.gate_status} - {summary.gate_reason}\n"
        f"Counts: {json.dumps(summary.verdict_counts, sort_keys=True)}",
        size=11,
    )
    _pdf_line(pdf, "Cases", size=12, bold=True)
    for case in summary.cases:
        _pdf_line(
            pdf,
            f"{case.case_id}  {case.verdict}  "
            f"{case.failed_attempts}/{case.valid_attempts}  {case.severity_if_violated}",
        )
    _pdf_line(pdf, "Attempts", size=12, bold=True)
    for attempt in summary.attempts:
        _pdf_line(
            pdf,
            f"{attempt.case_id}  {attempt.attempt_id}  {attempt.verdict}  {attempt.reason_code}",
        )
    return bytes(pdf.output())


def _pdf_line(pdf: FPDF, value: str, size: int = 10, bold: bool = False) -> None:
    pdf.set_font("Helvetica", "B" if bold else "", size)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pdf.epw, 6, _pdf_text(value))


def _pdf_text(value: str) -> str:
    cleaned = re.sub(r"(\S{40})", r"\1 ", value.replace("\u2014", "-"))
    return cleaned.encode("latin-1", "replace").decode("latin-1")


def _html(summary: RunSummary) -> str:
    rows = []
    for case in summary.cases:
        rows.append(
            "<tr>"
            f"<td>{html.escape(case.case_id)}</td>"
            f"<td>{html.escape(case.verdict)}</td>"
            f"<td>{case.failed_attempts}/{case.valid_attempts}</td>"
            f"<td>{html.escape(case.severity_if_violated)}</td>"
            "</tr>"
        )
    attempt_rows = []
    for attempt in summary.attempts:
        attempt_rows.append(
            "<tr>"
            f"<td>{html.escape(attempt.case_id)}</td>"
            f"<td>{html.escape(attempt.attempt_id)}</td>"
            f"<td>{html.escape(attempt.verdict)}</td>"
            f"<td>{html.escape(attempt.reason_code)}</td>"
            "</tr>"
        )
    counts = html.escape(json.dumps(summary.verdict_counts, sort_keys=True))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Assure report {html.escape(summary.run_id)}</title>
  <style>
    body {{ font-family: sans-serif; margin: 2rem; color: #111; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
    th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; }}
    .note {{ background: #f6f6f6; padding: 0.8rem; }}
  </style>
</head>
<body>
  <h1>Assure local report</h1>
  <p class="note">This report lists tested controls, verdicts, and coverage limits. It is not a security score and does not certify the application.</p>
  <p>Run: {html.escape(summary.run_id)}<br/>Build: {html.escape(summary.target_build)}<br/>Gate: {html.escape(summary.gate_status)} — {html.escape(summary.gate_reason)}<br/>Counts: {counts}</p>
  <h2>Cases</h2>
  <table>
    <thead><tr><th>Case</th><th>Verdict</th><th>Failed/valid attempts</th><th>Severity</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <h2>Attempts</h2>
  <table>
    <thead><tr><th>Case</th><th>Attempt</th><th>Verdict</th><th>Reason</th></tr></thead>
    <tbody>{''.join(attempt_rows)}</tbody>
  </table>
</body>
</html>
"""
