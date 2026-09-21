from __future__ import annotations

import re

from assure_contracts.adapters import FixtureHandle

_PLACEHOLDER = re.compile(r"\$\{([a-zA-Z0-9_]+)\}")


def render(template: str, fixture: FixtureHandle, attempt_id: str) -> str:
    bindings = {
        **fixture.bindings,
        **fixture.canaries,
        **fixture.resource_ids,
        "attempt_id": attempt_id,
        "namespace": fixture.namespace,
    }

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in bindings:
            raise ValueError(f"unknown placeholder: {key}")
        return bindings[key]

    return _PLACEHOLDER.sub(repl, template)
