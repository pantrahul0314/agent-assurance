from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from assure_contracts.enums import GateStatus
from assure_contracts.manifest import RunManifest
from assure_contracts.result import AttemptResult, CaseRollup, RunSummary
from assure_reporting.export import write_reports


def test_html_report_escapes_target_text(tmp_path: Path) -> None:
    summary = RunSummary.model_validate(
        {
            "schema": "assure/summary/v1",
            "run_id": "<script>alert(1)</script>",
            "environment_alias": "support_staging",
            "target_build": "demo",
            "suite_digest": "abc",
            "started_at": datetime.now(timezone.utc),
            "finished_at": datetime.now(timezone.utc),
            "verdict_counts": {"FAIL": 1},
            "cases": [
                CaseRollup(
                    case_id="TEN-01",
                    required_for_gate=True,
                    severity_if_violated="high",
                    verdict="FAIL",
                ).model_dump()
            ],
            "attempts": [
                AttemptResult.model_validate(
                    {
                        "schema": "assure/result/v1",
                        "case_id": "TEN-01",
                        "attempt_id": "a1",
                        "verdict": "FAIL",
                        "reason_code": "<img src=x onerror=alert(1)>",
                        "assertions": [],
                        "evidence_complete": True,
                        "target_build": "demo",
                    }
                ).model_dump(by_alias=True)
            ],
            "gate_status": GateStatus.BLOCKED_FINDING,
            "gate_reason": "blocked",
            "cleanup_ok": True,
        }
    )
    manifest = RunManifest.model_validate(
        {
            "schema": "assure/manifest/v1",
            "run_id": "r1",
            "environment_alias": "support_staging",
            "suite_digest": "abc",
            "cases": [],
            "target_alias": "support_staging",
            "target_build": "demo",
            "fixture_profile": "support_two_tenants",
        }
    )
    write_reports(tmp_path, summary, manifest)
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "security score" not in html.lower() or "not a security score" in html.lower()
    junit = (tmp_path / "report.junit.xml").read_text(encoding="utf-8")
    from xml.etree import ElementTree

    tree = ElementTree.fromstring(junit)
    assert tree.tag == "testsuite"
    assert tree.find("testcase") is not None
    assert "<script>alert(1)</script>" not in junit
    assert "<img src=x onerror=alert(1)>" not in junit
    pdf = (tmp_path / "report.pdf").read_bytes()
    assert pdf.startswith(b"%PDF")
    assert b"<script>" not in pdf
    assert b"CANARY-SECRET" not in pdf
