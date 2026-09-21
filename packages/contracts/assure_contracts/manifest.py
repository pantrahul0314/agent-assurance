from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from assure_contracts.enums import ExportMode
from assure_contracts.gate import GatePolicy


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SuiteInventory(StrictModel):
    case_id: str
    revision: int
    required_for_gate: bool
    repetitions: int
    severity_if_violated: str
    is_positive_control: bool = False


class RunManifest(StrictModel):
    schema_name: str = Field(alias="schema", default="assure/manifest/v1")
    run_id: str
    project_id: str | None = None
    environment_id: str | None = None
    environment_alias: str
    suite_digest: str
    suite_schema_version: str = "assure/v1"
    cases: list[SuiteInventory]
    target_alias: str
    target_build: str
    adapter_version: str = "1"
    runner_version: str = "0.1.0"
    fixture_profile: str
    fixture_profile_version: str = "1"
    observation_schema: str = "assure/events/v1"
    gate_policy: GatePolicy = Field(default_factory=GatePolicy)
    export_mode: ExportMode = ExportMode.SUMMARY
    budgets: dict[str, int] = Field(
        default_factory=lambda: {
            "max_attempts": 20,
            "deadline_seconds": 60,
            "max_turns": 4,
        }
    )
    approved_scope: list[str] = Field(
        default_factory=lambda: ["prepare_support_two_tenants", "cleanup_namespace"]
    )
