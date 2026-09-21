from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from assure_contracts.enums import GateStatus, Verdict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GatePolicy(StrictModel):
    block_on_high_fail: bool = True
    block_on_incomplete: bool = True
    require_positive_controls: bool = True


class GateDecision(StrictModel):
    status: GateStatus
    reason: str
    exit_code: int


def evaluate_gate(
    *,
    setup_ok: bool,
    cases: list[dict],
    policy: GatePolicy | None = None,
) -> GateDecision:
    policy = policy or GatePolicy()
    if not setup_ok:
        return GateDecision(
            status=GateStatus.BLOCKED_SETUP,
            reason="invalid setup or configuration",
            exit_code=3,
        )

    has_blocker = False
    has_incomplete = False
    reasons: list[str] = []

    for case in cases:
        verdict = Verdict(case["verdict"])
        required = bool(case.get("required_for_gate", True))
        severity = str(case.get("severity_if_violated", "high"))
        case_id = str(case.get("case_id", "unknown"))
        is_control = bool(case.get("is_positive_control", False))

        if is_control and policy.require_positive_controls and verdict != Verdict.PASS:
            has_incomplete = True
            reasons.append(f"{case_id}: positive control did not pass")
            continue

        if not required:
            continue

        if verdict == Verdict.FAIL and policy.block_on_high_fail and severity == "high":
            has_blocker = True
            reasons.append(f"{case_id}: confirmed high-severity finding")
        elif verdict in {Verdict.INCONCLUSIVE, Verdict.ERROR, Verdict.SKIPPED} and policy.block_on_incomplete:
            has_incomplete = True
            reasons.append(f"{case_id}: incomplete execution evidence ({verdict})")

    if has_blocker:
        return GateDecision(
            status=GateStatus.BLOCKED_FINDING,
            reason="; ".join(reasons),
            exit_code=1,
        )
    if has_incomplete:
        return GateDecision(
            status=GateStatus.BLOCKED_INCOMPLETE,
            reason="; ".join(reasons),
            exit_code=2,
        )
    return GateDecision(status=GateStatus.SATISFIED, reason="gate satisfied", exit_code=0)
