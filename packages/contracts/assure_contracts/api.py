from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from assure_contracts.enums import ExecutionStatus, ExportMode, GateStatus, Verdict
from assure_contracts.gate import GatePolicy
from assure_contracts.manifest import RunManifest, SuiteInventory
from assure_contracts.result import AttemptResult


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CreateProjectRequest(StrictModel):
    name: str
    export_mode: ExportMode = ExportMode.SUMMARY


class CreateEnvironmentRequest(StrictModel):
    local_alias: str
    permitted_scope: list[str] = Field(
        default_factory=lambda: ["prepare_support_two_tenants", "cleanup_namespace"]
    )
    export_mode: ExportMode = ExportMode.SUMMARY


class CreateSuiteRequest(StrictModel):
    name: str
    schema_version: str = "assure/v1"
    cases: list[SuiteInventory]
    digest: str | None = None


class CreateRunRequest(StrictModel):
    environment_id: str
    suite_id: str
    manifest: RunManifest
    idempotency_key: str


class AttemptBatchItem(StrictModel):
    attempt_id: str
    sequence: int
    content_digest: str
    result: AttemptResult


class AttemptBatchRequest(StrictModel):
    items: list[AttemptBatchItem] = Field(max_length=100)


class ArtifactPrepareRequest(StrictModel):
    filename: str
    content_digest: str
    content_type: str = "application/json"
    byte_size: int = Field(gt=0, le=1_000_000)


class CompleteRunRequest(StrictModel):
    target_build: str
    expected_attempt_ids: list[str]
    cleanup_ok: bool = True


class ExceptionRequest(StrictModel):
    reason: str
    expires_at: datetime


class GateView(StrictModel):
    status: GateStatus
    reason: str


class RunView(StrictModel):
    id: str
    org_id: str
    project_id: str
    environment_id: str
    suite_digest: str
    target_build: str | None
    execution_status: ExecutionStatus
    gate: GateView
    verdict_counts: dict[str, int] = Field(default_factory=dict)
    attempt_count: int = 0
    lease_epoch: int = 0
    created_at: datetime


# Re-export for callers that import api.Verdict
__all__ = [
    "ArtifactPrepareRequest",
    "AttemptBatchItem",
    "AttemptBatchRequest",
    "CompleteRunRequest",
    "CreateEnvironmentRequest",
    "CreateProjectRequest",
    "CreateRunRequest",
    "CreateSuiteRequest",
    "ExceptionRequest",
    "GatePolicy",
    "GateView",
    "RunView",
    "Verdict",
]
