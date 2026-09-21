from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from assure_contracts.enums import AssertionKind


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FixtureSpec(StrictModel):
    profile: str
    namespace: str = "${attempt_id}"


class PrincipalSpec(StrictModel):
    credential_ref: str
    expected_target_tenant: str


class PreconditionsSpec(StrictModel):
    fixture_exists: str | None = None
    positive_control_passed: str | None = None
    observation_source_ready: str | None = None


class ScenarioSpec(StrictModel):
    target_alias: str
    input: str
    max_turns: int = 4
    deadline_seconds: int = 60


class AssertionSpec(StrictModel):
    kind: AssertionKind
    resource_ref: str | None = None
    canary_ref: str | None = None
    tool_name: str | None = None
    expected_status: str | None = None


class StepSpec(StrictModel):
    credential_ref: str | None = None
    input: str
    session: str = "fresh"


class MidChangeSpec(StrictModel):
    kind: str
    resource_ref: str | None = None
    subject: str | None = None
    after_step: int = 0


class CompletionSpec(StrictModel):
    require_observation_receipt: bool = True
    require_all_declared_sources: bool = True


class CaseSpec(StrictModel):
    schema_name: str = Field(alias="schema", default="assure/v1")
    case_id: str
    revision: int = 1
    severity_if_violated: str = "high"
    required_for_gate: bool = True
    is_positive_control: bool = False
    disable_observation: bool = False
    fixture: FixtureSpec
    principal: PrincipalSpec
    preconditions: list[PreconditionsSpec] = Field(default_factory=list)
    scenario: ScenarioSpec
    assertions: list[AssertionSpec]
    completion: CompletionSpec = Field(default_factory=CompletionSpec)
    repetitions: int = 1
    expected_sources: list[str] = Field(
        default_factory=lambda: ["retrieval_returns", "response_capture", "tool_audit"]
    )
    steps: list[StepSpec] = Field(default_factory=list)
    mid_scenario_changes: list[MidChangeSpec] = Field(default_factory=list)
    retries: int = 0


def load_case(path: Path) -> CaseSpec:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return CaseSpec.model_validate(data)
