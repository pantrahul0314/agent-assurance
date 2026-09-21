from __future__ import annotations

from pathlib import Path

import pytest
from assure_contracts.enums import TargetMode, Verdict
from assure_runner.engine import run_suite

from tests.integration.conftest import make_config


@pytest.mark.asyncio
async def test_vulnerable_mode_fails_isolation(demo_env, suite_dir: Path, tmp_path: Path) -> None:
    store, adapters = demo_env
    store.mode = TargetMode.VULNERABLE
    summary, _manifest, code = await run_suite(make_config(), suite_dir, tmp_path, adapters=adapters)
    by_id = {item.case_id: item for item in summary.cases}
    assert by_id["POS-01"].verdict == Verdict.PASS
    assert by_id["TEN-01"].verdict == Verdict.FAIL
    assert by_id["TEN-02"].verdict == Verdict.FAIL
    assert by_id["TEN-03"].verdict == Verdict.FAIL
    assert by_id["ACT-01"].verdict == Verdict.FAIL
    assert by_id["ACT-02"].verdict == Verdict.FAIL
    assert by_id["ACT-03"].verdict == Verdict.FAIL
    assert by_id["INJ-01"].verdict == Verdict.FAIL
    assert by_id["INJ-02"].verdict == Verdict.FAIL
    assert by_id["REV-01"].verdict == Verdict.FAIL
    assert by_id["REV-02"].verdict == Verdict.FAIL
    assert by_id["REL-01"].verdict == Verdict.FAIL
    assert by_id["REL-02"].verdict == Verdict.FAIL
    assert by_id["OBS-01"].verdict == Verdict.INCONCLUSIVE
    assert code == 1
    ten = next(item for item in summary.attempts if item.case_id == "TEN-01")
    assert ten.reason_code == "FORBIDDEN_RESOURCE_RETURNED"


@pytest.mark.asyncio
async def test_safe_mode_passes_applicable_assertions(demo_env, suite_dir: Path, tmp_path: Path) -> None:
    store, adapters = demo_env
    store.mode = TargetMode.SAFE
    summary, _manifest, code = await run_suite(make_config(), suite_dir, tmp_path, adapters=adapters)
    by_id = {item.case_id: item for item in summary.cases}
    assert by_id["POS-01"].verdict == Verdict.PASS
    assert by_id["TEN-01"].verdict == Verdict.PASS
    assert by_id["TEN-02"].verdict == Verdict.PASS
    assert by_id["TEN-03"].verdict == Verdict.PASS
    assert by_id["ACT-01"].verdict == Verdict.PASS
    assert by_id["ACT-02"].verdict == Verdict.PASS
    assert by_id["ACT-03"].verdict == Verdict.PASS
    assert by_id["INJ-01"].verdict == Verdict.PASS
    assert by_id["INJ-02"].verdict == Verdict.PASS
    assert by_id["REV-01"].verdict == Verdict.PASS
    assert by_id["REV-02"].verdict == Verdict.PASS
    assert by_id["REL-01"].verdict == Verdict.PASS
    assert by_id["REL-02"].verdict == Verdict.PASS
    assert by_id["OBS-01"].verdict == Verdict.INCONCLUSIVE
    assert code == 2


@pytest.mark.asyncio
async def test_reject_all_cannot_satisfy_gate(demo_env, suite_dir: Path, tmp_path: Path) -> None:
    store, adapters = demo_env
    store.mode = TargetMode.REJECT_ALL
    summary, _manifest, code = await run_suite(make_config(), suite_dir, tmp_path, adapters=adapters)
    assert summary.cases[0].case_id == "POS-01"
    assert summary.cases[0].verdict != Verdict.PASS
    assert code in {1, 2}


@pytest.mark.asyncio
async def test_fail_preserved_across_repetition_budget(demo_env, suite_dir: Path, tmp_path: Path) -> None:
    store, adapters = demo_env
    store.mode = TargetMode.VULNERABLE
    summary, _manifest, _code = await run_suite(make_config(), suite_dir, tmp_path, adapters=adapters)
    ten_attempts = [item for item in summary.attempts if item.case_id == "TEN-01"]
    assert ten_attempts
    assert ten_attempts[0].verdict == Verdict.FAIL
    assert len(ten_attempts) == 1


@pytest.mark.asyncio
async def test_cleanup_quarantine(demo_env, tmp_path: Path) -> None:
    store, adapters = demo_env
    from assure_contracts.adapters import FixtureSpecRequest

    handle = await adapters.prepare(
        FixtureSpecRequest(profile="support_two_tenants", namespace="ns-fail")
    )
    store.namespaces["ns-fail"].fail_cleanup = True
    result = await adapters.cleanup(handle)
    assert result.ok is False
    assert result.quarantined is True
    with pytest.raises(Exception):
        await adapters.prepare(FixtureSpecRequest(profile="support_two_tenants", namespace="ns-fail"))
