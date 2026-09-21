from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from assure_contracts.enums import ExportMode
from assure_contracts.gate import GatePolicy


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            return os.environ.get(match.group(1), match.group(0))

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


class TargetConfig(StrictModel):
    alias: str
    base_url: str


class AdapterConfig(StrictModel):
    admin_token: str
    fixture_base_url: str
    observation_base_url: str


class ControlPlaneConfig(StrictModel):
    base_url: str = "http://127.0.0.1:8000"
    runner_token: str = ""
    project_id: str = ""
    environment_id: str = ""


class ExportConfig(StrictModel):
    mode: ExportMode = ExportMode.LOCAL
    output: str = "reports"


class BudgetConfig(StrictModel):
    max_attempts: int = 20
    deadline_seconds: int = 60
    max_turns: int = 4


class AssureConfig(StrictModel):
    schema_name: str = Field(alias="schema", default="assure/config/v1")
    target: TargetConfig
    credentials: dict[str, str]
    adapter: AdapterConfig
    control_plane: ControlPlaneConfig = Field(default_factory=ControlPlaneConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)
    gate: GatePolicy = Field(default_factory=GatePolicy)


def load_config(path: Path) -> AssureConfig:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AssureConfig.model_validate(_expand(data))
