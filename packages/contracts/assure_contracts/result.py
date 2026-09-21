from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from assure_contracts.enums import AssertionKind, AssertionStatus, GateStatus, Verdict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AssertionResult(StrictModel):
    kind: AssertionKind
    status: AssertionStatus
    reason: str | None = None


class AttemptResult(StrictModel):
    schema_name: str = Field(alias="schema", default="assure/result/v1")
    case_id: str
    attempt_id: str
    revision: int = 1
    variant: str = "default"
    repetition: int = 1
    verdict: Verdict
    scope: str = "retrieval_and_output"
    reason_code: str
    assertions: list[AssertionResult]
    evidence_complete: bool
    target_build: str
    fixture_profile_version: str = "1"
    observation_schema: str = "assure/events/v1"
    fixture_namespace: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class CaseRollup(StrictModel):
    case_id: str
    required_for_gate: bool
    severity_if_violated: str
    verdict: Verdict
    failed_attempts: int = 0
    valid_attempts: int = 0
    inconclusive_attempts: int = 0
    error_attempts: int = 0
    skipped_attempts: int = 0


class RunSummary(StrictModel):
    schema_name: str = Field(alias="schema", default="assure/summary/v1")
    run_id: str
    project_id: str | None = None
    environment_alias: str
    target_build: str
    suite_digest: str
    adapter_version: str = "1"
    runner_version: str = "0.1.0"
    started_at: datetime
    finished_at: datetime
    verdict_counts: dict[str, int]
    cases: list[CaseRollup]
    attempts: list[AttemptResult]
    gate_status: GateStatus
    gate_reason: str
    cleanup_ok: bool
    quarantined_namespaces: list[str] = Field(default_factory=list)
