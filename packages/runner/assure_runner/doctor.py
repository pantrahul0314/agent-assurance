from __future__ import annotations

from assure_adapters.http import DemoAdapters, PolicyError
from assure_contracts.adapters import ApprovedScope, FixtureSpecRequest
from assure_contracts.config import AssureConfig


async def run_doctor(config: AssureConfig, adapters: DemoAdapters | None = None) -> tuple[bool, list[str]]:
    own = adapters is None
    adapters = adapters or DemoAdapters(config)
    errors: list[str] = []
    try:
        try:
            build = await adapters.identify_build()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"build identity unavailable: {exc}")
            build = None
        scope = ApprovedScope(target_alias=config.target.alias, fixture_profile="support_two_tenants")
        preflight = await adapters.preflight(scope)
        errors.extend(preflight.errors)
        if not preflight.fixture_access:
            errors.append("fixture access unavailable")
        if not preflight.observation_available:
            errors.append("observation channel unavailable")
        if not preflight.cleanup_available:
            errors.append("cleanup unavailable")
        missing = [name for name, token in config.credentials.items() if not token or token.startswith("${")]
        if missing:
            errors.append(f"unresolved credentials: {', '.join(missing)}")
        handle = await adapters.prepare(FixtureSpecRequest(profile="support_two_tenants", namespace="doctor-check"))
        state = await adapters.verify(handle)
        if not state.exists:
            errors.append("fixture verify failed")
        cleanup = await adapters.cleanup(handle)
        if not cleanup.ok:
            errors.append("cleanup failed")
        if build is None:
            errors.append("target build missing")
    except PolicyError as exc:
        errors.append(str(exc))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"doctor failed: {exc}")
    finally:
        if own:
            await adapters.aclose()
    return not errors, errors
