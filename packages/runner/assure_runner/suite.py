from __future__ import annotations

from pathlib import Path

from assure_contracts.case import CaseSpec, load_case


def load_suite(path: Path) -> list[CaseSpec]:
    if path.is_file():
        cases = [load_case(path)]
    else:
        cases = [load_case(item) for item in sorted(path.glob("*.yaml"))]
    if not cases:
        raise ValueError(f"no cases found in {path}")
    cases.sort(key=lambda case: (not case.is_positive_control, case.case_id))
    return cases
