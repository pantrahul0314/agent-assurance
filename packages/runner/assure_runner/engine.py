from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from assure_adapters.http import DemoAdapters
from assure_assertions.engine import evaluate_attempt, rollup_case
from assure_contracts.adapters import (
    ApprovedFixtureChange,
    ApprovedScope,
    AttemptContext,
    FixtureHandle,
    FixtureSpecRequest,
    ScenarioRequest,
)
from assure_contracts.case import CaseSpec, MidChangeSpec, StepSpec
from assure_contracts.config import AssureConfig
from assure_contracts.enums import Verdict
from assure_contracts.gate import evaluate_gate
from assure_contracts.manifest import RunManifest, SuiteInventory
from assure_contracts.result import AttemptResult, CaseRollup, RunSummary
from assure_reporting.export import write_reports
from assure_runner.placeholders import render
from assure_runner.suite import load_suite


async def run_suite(
    config: AssureConfig,
    suite_path: Path,
    output_dir: Path,
    adapters: DemoAdapters | None = None,
    run_id: str | None = None,
) -> tuple[RunSummary, RunManifest, int]:
    cases = load_suite(suite_path)
    own_adapters = adapters is None
    adapters = adapters or DemoAdapters(config)
    started = datetime.now(timezone.utc)
    run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
    quarantined: list[str] = []
    attempts: list[AttemptResult] = []
    rollups: list[CaseRollup] = []
    setup_ok = True
    target_build = "unknown"

    try:
        scope = ApprovedScope(target_alias=config.target.alias, fixture_profile="support_two_tenants")
        preflight = await adapters.preflight(scope)
        build = await adapters.identify_build()
        target_build = build.build_id
        if not preflight.ok:
            setup_ok = False
        for case in cases:
            case_attempts: list[AttemptResult] = []
            for repetition in range(1, case.repetitions + 1):
                attempt = await _run_attempt(
                    adapters,
                    config,
                    case,
                    run_id,
                    repetition,
                    target_build,
                )
                if attempt.fixture_namespace and "quarantine" in attempt.reason_code.lower():
                    quarantined.append(attempt.fixture_namespace)
                case_attempts.append(attempt)
                attempts.append(attempt)
                if attempt.verdict == Verdict.FAIL:
                    break
            rollups.append(rollup_case(case, case_attempts))
    finally:
        if own_adapters:
            await adapters.aclose()

    finished = datetime.now(timezone.utc)
    counts = {verdict.value: 0 for verdict in Verdict}
    for rollup in rollups:
        counts[rollup.verdict] = counts.get(rollup.verdict, 0) + 1

    gate = evaluate_gate(
        setup_ok=setup_ok,
        cases=[
            {
                "case_id": item.case_id,
                "verdict": item.verdict,
                "required_for_gate": item.required_for_gate,
                "severity_if_violated": item.severity_if_violated,
                "is_positive_control": next(
                    case.is_positive_control for case in cases if case.case_id == item.case_id
                ),
            }
            for item in rollups
        ],
        policy=config.gate,
    )
    digest = hashlib.sha256(
        "".join(f"{case.case_id}:{case.revision}:{case.repetitions}" for case in cases).encode()
    ).hexdigest()[:16]
    summary = RunSummary.model_validate(
        {
            "schema": "assure/summary/v1",
            "run_id": run_id,
            "project_id": config.control_plane.project_id or None,
            "environment_alias": config.target.alias,
            "target_build": target_build,
            "suite_digest": digest,
            "started_at": started,
            "finished_at": finished,
            "verdict_counts": counts,
            "cases": [item.model_dump() for item in rollups],
            "attempts": [item.model_dump(by_alias=True) for item in attempts],
            "gate_status": gate.status,
            "gate_reason": gate.reason,
            "cleanup_ok": not quarantined,
            "quarantined_namespaces": quarantined,
        }
    )
    manifest = RunManifest.model_validate(
        {
            "schema": "assure/manifest/v1",
            "run_id": run_id,
            "project_id": config.control_plane.project_id or None,
            "environment_id": config.control_plane.environment_id or None,
            "environment_alias": config.target.alias,
            "suite_digest": digest,
            "cases": [
                SuiteInventory(
                    case_id=case.case_id,
                    revision=case.revision,
                    required_for_gate=case.required_for_gate,
                    repetitions=case.repetitions,
                    severity_if_violated=case.severity_if_violated,
                    is_positive_control=case.is_positive_control,
                ).model_dump()
                for case in cases
            ],
            "target_alias": config.target.alias,
            "target_build": target_build,
            "fixture_profile": "support_two_tenants",
            "gate_policy": config.gate.model_dump(),
            "export_mode": config.export.mode,
            "budgets": {
                "max_attempts": config.budgets.max_attempts,
                "deadline_seconds": config.budgets.deadline_seconds,
                "max_turns": config.budgets.max_turns,
            },
        }
    )
    write_reports(output_dir, summary, manifest)
    return summary, manifest, gate.exit_code


async def _run_attempt(
    adapters: DemoAdapters,
    config: AssureConfig,
    case: CaseSpec,
    run_id: str,
    repetition: int,
    target_build: str,
) -> AttemptResult:
    attempt_id = f"{run_id}-{case.case_id}-r{repetition}-{uuid.uuid4().hex[:8]}"
    namespace = attempt_id
    fixture = FixtureHandle(namespace=namespace, profile=case.fixture.profile)
    observer_disabled = case.disable_observation
    try:
        if observer_disabled:
            await adapters.set_observer(False)
        fixture = await adapters.prepare(
            FixtureSpecRequest(profile=case.fixture.profile, namespace=namespace)
        )
        state = await adapters.verify(fixture)
        if not state.exists:
            raise RuntimeError("fixture missing after prepare")
        cursor = None
        if not observer_disabled:
            cursor = await adapters.begin(
                AttemptContext(
                    attempt_id=attempt_id,
                    correlation_id=attempt_id,
                    namespace=namespace,
                    declared_sources=case.expected_sources,
                )
            )
        conversation = await _invoke_case(adapters, case, fixture, attempt_id)
        evidence = None
        if cursor is not None:
            evidence = await adapters.finish(cursor)
        snapshot = await adapters.snapshot(fixture)
        result = evaluate_attempt(
            case=case,
            attempt_id=attempt_id,
            repetition=repetition,
            fixture=fixture,
            evidence=evidence,
            snapshot=snapshot,
            output_text=conversation.output_text,
            target_build=target_build,
            observation_forced_unavailable=observer_disabled,
        )
        cleanup = await adapters.cleanup(fixture)
        if not cleanup.ok:
            result = result.model_copy(
                update={"reason_code": "CLEANUP_QUARANTINE", "verdict": result.verdict}
            )
        return result
    except Exception as exc:  # noqa: BLE001 - convert harness failures to ERROR
        return AttemptResult.model_validate(
            {
                "schema": "assure/result/v1",
                "case_id": case.case_id,
                "attempt_id": attempt_id,
                "revision": case.revision,
                "repetition": repetition,
                "verdict": Verdict.ERROR,
                "reason_code": f"HARNESS_ERROR:{exc.__class__.__name__}",
                "assertions": [],
                "evidence_complete": False,
                "target_build": target_build,
                "fixture_namespace": namespace,
            }
        )
    finally:
        if observer_disabled:
            try:
                await adapters.set_observer(True)
            except Exception:
                pass


async def _invoke_case(adapters: DemoAdapters, case: CaseSpec, fixture: FixtureHandle, attempt_id: str):
    steps = case.steps or [
        StepSpec(credential_ref=case.principal.credential_ref, input=case.scenario.input, session="fresh")
    ]
    sessions: dict[str, str] = {}
    conversation = None
    await _apply_changes(adapters, case.mid_scenario_changes, fixture.namespace, after_step=0)
    last_request: ScenarioRequest | None = None
    for index, step in enumerate(steps, start=1):
        if step.session == "fresh":
            session_id = f"{attempt_id}-s{index}"
        else:
            session_id = sessions.setdefault(step.session, f"{attempt_id}-{step.session}")
        request = ScenarioRequest(
            credential_ref=step.credential_ref or case.principal.credential_ref,
            session_id=session_id,
            input_text=render(step.input, fixture, attempt_id),
            correlation_id=attempt_id,
            max_turns=case.scenario.max_turns,
        )
        conversation = await adapters.invoke(request)
        last_request = request
        await _apply_changes(adapters, case.mid_scenario_changes, fixture.namespace, after_step=index)
    if last_request is None:
        raise RuntimeError("case produced no scenario steps")
    for _ in range(case.retries):
        conversation = await adapters.invoke(last_request)
    if conversation is None:
        raise RuntimeError("case produced no conversation")
    return conversation


async def _apply_changes(
    adapters: DemoAdapters,
    changes: list[MidChangeSpec],
    namespace: str,
    after_step: int,
) -> None:
    for change in changes:
        if change.after_step != after_step:
            continue
        payload: dict[str, str] = {}
        if change.resource_ref:
            payload["resource_ref"] = change.resource_ref
        if change.subject:
            payload["subject"] = change.subject
        await adapters.apply_test_change(
            ApprovedFixtureChange(kind=change.kind, namespace=namespace, payload=payload)
        )
