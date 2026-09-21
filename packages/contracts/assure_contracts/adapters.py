from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from assure_contracts.enums import TargetMode
from assure_contracts.events import NormalizedFact, ObservationEvent


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TargetBuild(StrictModel):
    build_id: str
    mode: TargetMode
    model_identifier: str = "deterministic-keyword-router"
    policy_version: str = "support-policy/v1"


class ScenarioRequest(StrictModel):
    credential_ref: str
    session_id: str
    input_text: str
    correlation_id: str
    max_turns: int = 4


class ToolInvocation(StrictModel):
    name: str
    requested: bool = True
    executed: bool = False
    arguments: dict[str, str] = Field(default_factory=dict)
    resource_ids: list[str] = Field(default_factory=list)


class ConversationTurn(StrictModel):
    role: str
    text: str


class ConversationResult(StrictModel):
    output_text: str
    turns: list[ConversationTurn] = Field(default_factory=list)
    tools: list[ToolInvocation] = Field(default_factory=list)
    correlation_id: str


class ApprovedScope(StrictModel):
    target_alias: str
    fixture_profile: str
    allowed_mutations: list[str] = Field(
        default_factory=lambda: ["prepare_support_two_tenants", "cleanup_namespace"]
    )


class PreflightResult(StrictModel):
    ok: bool
    build: TargetBuild | None = None
    principals: list[str] = Field(default_factory=list)
    fixture_access: bool = False
    observation_available: bool = False
    cleanup_available: bool = False
    errors: list[str] = Field(default_factory=list)


class FixtureSpecRequest(StrictModel):
    profile: str
    namespace: str


class FixtureHandle(StrictModel):
    namespace: str
    profile: str
    profile_version: str = "1"
    bindings: dict[str, str] = Field(default_factory=dict)
    canaries: dict[str, str] = Field(default_factory=dict)
    resource_ids: dict[str, str] = Field(default_factory=dict)


class FixtureState(StrictModel):
    namespace: str
    exists: bool
    quarantined: bool = False
    tickets: dict[str, str] = Field(default_factory=dict)


class ApprovedFixtureChange(StrictModel):
    kind: str
    namespace: str
    payload: dict[str, str] = Field(default_factory=dict)


class Receipt(StrictModel):
    accepted: bool
    detail: str = ""


class CleanupResult(StrictModel):
    ok: bool
    namespace: str
    quarantined: bool = False
    detail: str = ""


class AttemptContext(StrictModel):
    attempt_id: str
    correlation_id: str
    namespace: str
    declared_sources: list[str] = Field(
        default_factory=lambda: ["retrieval_returns", "response_capture", "tool_audit"]
    )


class ObservationCursor(StrictModel):
    attempt_id: str
    correlation_id: str
    started_at: datetime
    start_sequence: int = 0
    disabled: bool = False
    declared_sources: list[str] = Field(
        default_factory=lambda: ["retrieval_returns", "response_capture", "tool_audit"]
    )


class StateSnapshot(StrictModel):
    namespace: str
    tickets: dict[str, dict[str, str]] = Field(default_factory=dict)
    captured_at: datetime


class EvidenceEnvelope(StrictModel):
    expected_sources: list[str]
    observed_sources: list[str]
    sequence_start: int
    sequence_end: int
    completion_status: str
    observation_started_at: datetime
    observation_finished_at: datetime
    facts: list[NormalizedFact] = Field(default_factory=list)
    events: list[ObservationEvent] = Field(default_factory=list)
    receipt: bool = False


class TargetClient(Protocol):
    async def identify_build(self) -> TargetBuild: ...
    async def invoke(self, request: ScenarioRequest) -> ConversationResult: ...


class FixtureAdapter(Protocol):
    async def preflight(self, scope: ApprovedScope) -> PreflightResult: ...
    async def prepare(self, spec: FixtureSpecRequest) -> FixtureHandle: ...
    async def verify(self, fixture: FixtureHandle) -> FixtureState: ...
    async def apply_test_change(self, change: ApprovedFixtureChange) -> Receipt: ...
    async def cleanup(self, fixture: FixtureHandle) -> CleanupResult: ...


class ObservationAdapter(Protocol):
    async def begin(self, context: AttemptContext) -> ObservationCursor: ...
    async def finish(self, cursor: ObservationCursor) -> EvidenceEnvelope: ...
    async def snapshot(self, fixture: FixtureHandle) -> StateSnapshot: ...
