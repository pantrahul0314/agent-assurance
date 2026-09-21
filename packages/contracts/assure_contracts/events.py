from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthzDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    BYPASS = "bypass"


class NormalizedFact(StrictModel):
    authenticated_subject: str
    active_tenant: str
    resources_returned: list[str] = Field(default_factory=list)
    resource_contents: dict[str, str] = Field(default_factory=dict)
    tool_requested: str | None = None
    tool_executed: str | None = None
    authz_decision: AuthzDecision | None = None
    policy_version: str = "support-policy/v1"
    committed_action_id: str | None = None
    output_text: str = ""
    canaries_seen: list[str] = Field(default_factory=list)


class ObservationEvent(StrictModel):
    schema_name: str = Field(alias="schema", default="assure/events/v1")
    sequence: int
    timestamp: datetime
    correlation_id: str
    source: str
    fact: NormalizedFact
