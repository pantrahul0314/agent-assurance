from __future__ import annotations

import pytest
from pydantic import ValidationError

from assure_contracts.case import CaseSpec
from assure_contracts.gate import evaluate_gate
from assure_contracts.result import AttemptResult


def test_case_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CaseSpec.model_validate(
            {
                "schema": "assure/v1",
                "case_id": "TEN-01",
                "fixture": {"profile": "support_two_tenants"},
                "principal": {"credential_ref": "tenant_a_reader", "expected_target_tenant": "tenant_a"},
                "scenario": {"target_alias": "support_staging", "input": "hello"},
                "assertions": [{"kind": "forbidden_canary_not_in_output", "canary_ref": "tenant_b_canary"}],
                "shell": "rm -rf /",
            }
        )


def test_result_shape() -> None:
    result = AttemptResult.model_validate(
        {
            "schema": "assure/result/v1",
            "case_id": "TEN-01",
            "attempt_id": "attempt_123",
            "verdict": "FAIL",
            "reason_code": "FORBIDDEN_RESOURCE_RETURNED",
            "assertions": [
                {"kind": "forbidden_resource_not_returned_to_agent", "status": "FAIL"},
                {"kind": "forbidden_canary_not_in_output", "status": "PASS"},
            ],
            "evidence_complete": True,
            "target_build": "example-commit-id",
        }
    )
    assert result.verdict == "FAIL"
    assert result.evidence_complete is True


def test_gate_distinguishes_finding_from_incomplete() -> None:
    blocked = evaluate_gate(
        setup_ok=True,
        cases=[{"case_id": "TEN-01", "verdict": "FAIL", "required_for_gate": True, "severity_if_violated": "high"}],
    )
    incomplete = evaluate_gate(
        setup_ok=True,
        cases=[{"case_id": "OBS-01", "verdict": "INCONCLUSIVE", "required_for_gate": True, "severity_if_violated": "high"}],
    )
    setup = evaluate_gate(setup_ok=False, cases=[])
    assert blocked.exit_code == 1
    assert incomplete.exit_code == 2
    assert setup.exit_code == 3
