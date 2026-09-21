from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from assure_contracts.api import (
    ArtifactPrepareRequest,
    AttemptBatchRequest,
    CompleteRunRequest,
    CreateEnvironmentRequest,
    CreateProjectRequest,
    CreateRunRequest,
    CreateSuiteRequest,
    ExceptionRequest,
    GateView,
    RunView,
)
from assure_contracts.enums import ExecutionStatus, GateStatus, Verdict
from assure_contracts.gate import evaluate_gate
from assure_contracts.manifest import RunManifest
from assure_contracts.result import AttemptResult, CaseRollup, RunSummary
from assure_reporting.export import html_report, junit_report, pdf_report
from assure_control_api.auth import Principal
from assure_control_api.oidc import (
    GithubExchangeRequest,
    SESSION_COOKIE,
    establish_session,
    exchange_github_oidc,
    login_redirect,
)
from assure_control_api.models import (
    Artifact,
    Attempt,
    AuditEvent,
    Environment,
    Finding,
    Project,
    RiskException,
    Run,
    SuiteVersion,
    WorkItem,
    new_id,
    utcnow,
)


def build_router(get_session, get_principal) -> APIRouter:
    router = APIRouter()

    def editor(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in {"editor"}:
            raise HTTPException(status_code=403, detail="editor role required")
        return principal

    def viewer(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in {"editor", "viewer", "runner"}:
            raise HTTPException(status_code=403, detail="viewer role required")
        return principal

    def runner(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in {"editor", "runner"}:
            raise HTTPException(status_code=403, detail="runner role required")
        return principal

    def audit(session: Session, principal: Principal, event: str, object_ref: str) -> None:
        session.add(AuditEvent(org_id=principal.org_id, actor=principal.subject, event=event, object_ref=object_ref))

    @router.get("/v1/auth/oidc/config")
    def oidc_config(request: Request) -> dict:
        settings = request.app.state.oidc
        return {"enabled": settings.enabled, "login_path": "/v1/auth/oidc/login"}

    @router.get("/v1/auth/oidc/login")
    def oidc_login(request: Request) -> RedirectResponse:
        settings = request.app.state.oidc
        if not settings.enabled:
            raise HTTPException(status_code=404, detail="OIDC is not configured")
        return RedirectResponse(login_redirect(settings), status_code=302)

    @router.get("/v1/auth/oidc/callback")
    def oidc_callback(
        request: Request,
        code: str,
        state: str,
        session: Session = Depends(get_session),
    ) -> RedirectResponse:
        settings = request.app.state.oidc
        if not settings.enabled:
            raise HTTPException(status_code=404, detail="OIDC is not configured")
        if state not in settings.pending_states:
            raise HTTPException(status_code=401, detail="invalid OIDC state")
        settings.pending_states.pop(state, None)
        claims = request.app.state.oidc_claim_loader(settings, code)
        try:
            row = establish_session(session, claims)
        except LookupError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        audit(session, Principal(row.org_id, row.subject, row.role, row.environment_id, row.id), "oidc.login", row.id)
        response = RedirectResponse("http://127.0.0.1:5173/setup", status_code=302)
        response.set_cookie(SESSION_COOKIE, row.id, httponly=True, samesite="lax", secure=False)
        return response

    @router.post("/v1/auth/logout")
    def oidc_logout() -> Response:
        response = Response(status_code=204)
        response.delete_cookie(SESSION_COOKIE)
        return response

    @router.post("/v1/ci/oidc/exchange")
    def ci_oidc_exchange(
        body: GithubExchangeRequest,
        request: Request,
        session: Session = Depends(get_session),
    ) -> dict:
        try:
            token, principal = exchange_github_oidc(
                session,
                body.jwt,
                jwks=request.app.state.ci_jwks,
                environment_id=body.environment_id,
            )
        except PermissionError as exc:
            session.add(
                AuditEvent(org_id="unknown", actor="ci", event="oidc.exchange.deny", object_ref=str(exc)[:180])
            )
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        audit(session, principal, "oidc.exchange.accept", principal.credential_id)
        return {"token": token, "org_id": principal.org_id, "role": principal.role, "environment_id": principal.environment_id}

    @router.get("/v1/me")
    def me(principal: Principal = Depends(get_principal)) -> dict:
        return {
            "org_id": principal.org_id,
            "subject": principal.subject,
            "role": principal.role,
            "environment_id": principal.environment_id,
        }

    @router.get("/v1/projects")
    def list_projects(session: Session = Depends(get_session), principal: Principal = Depends(viewer)) -> list[dict]:
        rows = session.query(Project).filter_by(org_id=principal.org_id).all()
        return [_project_view(row) for row in rows]

    @router.post("/v1/projects")
    def create_project(
        body: CreateProjectRequest,
        session: Session = Depends(get_session),
        principal: Principal = Depends(editor),
    ) -> dict:
        row = Project(
            org_id=principal.org_id,
            name=body.name,
            owner_subject=principal.subject,
            export_mode=str(body.export_mode),
        )
        session.add(row)
        session.flush()
        audit(session, principal, "project.create", row.id)
        return _project_view(row)

    @router.post("/v1/projects/{project_id}/environments")
    def create_environment(
        project_id: str,
        body: CreateEnvironmentRequest,
        session: Session = Depends(get_session),
        principal: Principal = Depends(editor),
    ) -> dict:
        project = _project(session, principal.org_id, project_id)
        row = Environment(
            org_id=principal.org_id,
            project_id=project.id,
            local_alias=body.local_alias,
            permitted_scope=json.dumps(body.permitted_scope),
            export_mode=str(body.export_mode),
        )
        session.add(row)
        session.flush()
        audit(session, principal, "environment.create", row.id)
        return _env_view(row)

    @router.get("/v1/projects/{project_id}/environments")
    def list_environments(
        project_id: str,
        session: Session = Depends(get_session),
        principal: Principal = Depends(viewer),
    ) -> list[dict]:
        _project(session, principal.org_id, project_id)
        rows = session.query(Environment).filter_by(org_id=principal.org_id, project_id=project_id).all()
        return [_env_view(row) for row in rows]

    @router.post("/v1/suites")
    def create_suite(
        body: CreateSuiteRequest,
        session: Session = Depends(get_session),
        principal: Principal = Depends(editor),
    ) -> dict:
        digest = body.digest or new_id()
        row = SuiteVersion(
            org_id=principal.org_id,
            name=body.name,
            digest=digest,
            schema_version=body.schema_version,
            case_inventory=json.dumps([item.model_dump() for item in body.cases]),
        )
        session.add(row)
        session.flush()
        return {"id": row.id, "digest": row.digest}

    @router.post("/v1/runs")
    def create_run(
        body: CreateRunRequest,
        session: Session = Depends(get_session),
        principal: Principal = Depends(runner),
    ) -> dict:
        existing = (
            session.query(Run)
            .filter_by(org_id=principal.org_id, idempotency_key=body.idempotency_key)
            .one_or_none()
        )
        if existing:
            return _run_view(existing, session)
        env = session.query(Environment).filter_by(id=body.environment_id, org_id=principal.org_id).one_or_none()
        if env is None:
            raise HTTPException(status_code=404, detail="environment not found")
        if principal.role == "runner" and principal.environment_id and principal.environment_id != env.id:
            raise HTTPException(status_code=403, detail="runner not bound to environment")
        if "://" in body.manifest.target_alias or body.manifest.target_alias != env.local_alias:
            raise HTTPException(status_code=400, detail="target alias is not in the approved local scope")
        manifest = body.manifest.model_copy(
            update={"project_id": env.project_id, "environment_id": env.id}
        )
        _upsert_suite(session, principal.org_id, manifest)
        row = Run(
            org_id=principal.org_id,
            project_id=env.project_id,
            environment_id=env.id,
            suite_digest=manifest.suite_digest,
            manifest=manifest.model_dump_json(by_alias=True),
            target_build=manifest.target_build,
            idempotency_key=body.idempotency_key,
        )
        session.add(row)
        session.flush()
        audit(session, principal, "run.create", row.id)
        return _run_view(row, session)

    @router.post("/v1/runs/{run_id}/claim")
    def claim_run(
        run_id: str,
        session: Session = Depends(get_session),
        principal: Principal = Depends(runner),
    ) -> dict:
        row = _run(session, principal.org_id, run_id)
        if principal.role == "runner" and principal.environment_id and principal.environment_id != row.environment_id:
            raise HTTPException(status_code=403, detail="runner not bound to run environment")
        if row.execution_status not in {ExecutionStatus.REGISTERED, ExecutionStatus.RUNNING}:
            raise HTTPException(status_code=409, detail="run cannot be claimed")
        row.execution_status = ExecutionStatus.RUNNING
        row.lease_epoch += 1
        row.lease_token = new_id()
        row.lease_expires_at = utcnow() + timedelta(minutes=15)
        audit(session, principal, "run.claim", row.id)
        return {"run_id": row.id, "lease_token": row.lease_token, "lease_epoch": row.lease_epoch}

    @router.post("/v1/runs/{run_id}/heartbeat")
    def heartbeat(
        run_id: str,
        session: Session = Depends(get_session),
        principal: Principal = Depends(runner),
    ) -> dict:
        row = _run(session, principal.org_id, run_id)
        if row.execution_status != ExecutionStatus.RUNNING:
            raise HTTPException(status_code=409, detail="run is not running")
        row.lease_expires_at = utcnow() + timedelta(minutes=15)
        return {"ok": True, "execution_status": row.execution_status}

    @router.post("/v1/runs/{run_id}/attempts:batch")
    def upload_attempts(
        run_id: str,
        body: AttemptBatchRequest,
        session: Session = Depends(get_session),
        principal: Principal = Depends(runner),
    ) -> dict:
        row = _run(session, principal.org_id, run_id)
        accepted = 0
        for item in body.items:
            existing = (
                session.query(Attempt)
                .filter_by(org_id=principal.org_id, run_id=row.id, attempt_id=item.attempt_id)
                .one_or_none()
            )
            payload = item.result.model_dump_json(by_alias=True)
            if existing:
                if existing.content_digest != item.content_digest:
                    audit(session, principal, "attempt.conflict", item.attempt_id)
                    raise HTTPException(status_code=409, detail="conflicting attempt reuse")
                accepted += 1
                continue
            session.add(
                Attempt(
                    org_id=principal.org_id,
                    run_id=row.id,
                    attempt_id=item.attempt_id,
                    case_id=item.result.case_id,
                    revision=item.result.revision,
                    variant=item.result.variant,
                    repetition=item.result.repetition,
                    fixture_namespace=item.result.fixture_namespace,
                    verdict=item.result.verdict,
                    evidence_status="complete" if item.result.evidence_complete else "incomplete",
                    result_json=payload,
                    content_digest=item.content_digest,
                    sequence=item.sequence,
                )
            )
            if item.result.verdict == Verdict.FAIL:
                _upsert_finding(session, row, item.result.case_id, item.result.reason_code, item.result.scope)
            accepted += 1
        row.execution_status = ExecutionStatus.UPLOADING
        return {"accepted": accepted}

    @router.post("/v1/runs/{run_id}/artifacts:prepare")
    def prepare_artifact(
        run_id: str,
        body: ArtifactPrepareRequest,
        session: Session = Depends(get_session),
        principal: Principal = Depends(runner),
    ) -> dict:
        row = _run(session, principal.org_id, run_id)
        if "/" in body.filename or "\\" in body.filename or body.filename.startswith("."):
            raise HTTPException(status_code=400, detail="invalid filename")
        artifact_id = new_id()
        key = f"{principal.org_id}/{row.id}/{artifact_id}-{body.filename}"
        artifact = Artifact(
            id=artifact_id,
            org_id=principal.org_id,
            run_id=row.id,
            object_key=key,
            content_digest=body.content_digest,
        )
        session.add(artifact)
        session.flush()
        return {"artifact_id": artifact.id, "object_key": key, "upload_path": f"/v1/artifacts/{artifact.id}"}

    @router.put("/v1/artifacts/{artifact_id}")
    async def upload_artifact(
        artifact_id: str,
        request: Request,
        session: Session = Depends(get_session),
        principal: Principal = Depends(runner),
    ) -> dict:
        row = session.query(Artifact).filter_by(id=artifact_id, org_id=principal.org_id, deleted=False).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        root = Path(os.environ.get("ASSURE_ARTIFACT_DIR", ".assure-artifacts"))
        path = root / row.object_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(await request.body())
        return {"ok": True}

    @router.post("/v1/runs/{run_id}/complete")
    def complete_run(
        run_id: str,
        body: CompleteRunRequest,
        session: Session = Depends(get_session),
        principal: Principal = Depends(runner),
    ) -> dict:
        row = _run(session, principal.org_id, run_id)
        if row.execution_status == ExecutionStatus.INCOMPLETE:
            raise HTTPException(status_code=409, detail="stale lease cannot finalize")
        if row.execution_status == ExecutionStatus.CANCEL_REQUESTED:
            row.execution_status = ExecutionStatus.CANCELLED
            row.gate_status = GateStatus.BLOCKED_INCOMPLETE
            row.gate_reason = "run cancelled; cancellation is not proof that target side effects stopped"
            return _run_view(row, session)
        stored = session.query(Attempt).filter_by(org_id=principal.org_id, run_id=row.id).all()
        stored_ids = {item.attempt_id for item in stored}
        expected = set(body.expected_attempt_ids)
        if stored_ids != expected:
            row.execution_status = ExecutionStatus.INCOMPLETE
            row.gate_status = GateStatus.BLOCKED_INCOMPLETE
            row.gate_reason = "required attempts missing or unexpected"
            return _run_view(row, session)
        row.target_build = body.target_build
        row.cleanup_ok = body.cleanup_ok
        _apply_gate(row, stored)
        if any(item.verdict == Verdict.FAIL for item in stored):
            for finding in session.query(Finding).filter_by(org_id=row.org_id, project_id=row.project_id).all():
                if finding.last_seen_run_id != row.id and finding.disposition == "open":
                    finding.disposition = "not_observed_in_retest"
        row.execution_status = ExecutionStatus.COMPLETED
        audit(session, principal, "run.complete", row.id)
        return _run_view(row, session)

    @router.post("/v1/runs/{run_id}/cancel")
    def cancel_run(
        run_id: str,
        session: Session = Depends(get_session),
        principal: Principal = Depends(editor),
    ) -> dict:
        row = _run(session, principal.org_id, run_id)
        if row.execution_status in {ExecutionStatus.COMPLETED, ExecutionStatus.CANCELLED}:
            raise HTTPException(status_code=409, detail="run already finished")
        row.execution_status = ExecutionStatus.CANCEL_REQUESTED
        row.gate_status = GateStatus.NOT_EVALUATED
        row.gate_reason = "cancellation requested; waiting for runner acknowledgment"
        audit(session, principal, "run.cancel", row.id)
        return _run_view(row, session)

    @router.get("/v1/runs/{run_id}")
    def get_run(
        run_id: str,
        session: Session = Depends(get_session),
        principal: Principal = Depends(viewer),
    ) -> dict:
        return _run_view(_run(session, principal.org_id, run_id), session)

    @router.get("/v1/projects/{project_id}/runs")
    def list_runs(
        project_id: str,
        session: Session = Depends(get_session),
        principal: Principal = Depends(viewer),
    ) -> list[dict]:
        _project(session, principal.org_id, project_id)
        rows = (
            session.query(Run)
            .filter_by(org_id=principal.org_id, project_id=project_id)
            .order_by(Run.created_at.desc())
            .all()
        )
        return [_run_view(row, session) for row in rows]

    @router.get("/v1/projects/{project_id}/findings")
    def list_findings(
        project_id: str,
        session: Session = Depends(get_session),
        principal: Principal = Depends(viewer),
    ) -> list[dict]:
        _project(session, principal.org_id, project_id)
        rows = session.query(Finding).filter_by(org_id=principal.org_id, project_id=project_id).all()
        return [_finding_view(row) for row in rows]

    @router.get("/v1/findings/{finding_id}")
    def get_finding(
        finding_id: str,
        session: Session = Depends(get_session),
        principal: Principal = Depends(viewer),
    ) -> dict:
        row = session.query(Finding).filter_by(id=finding_id, org_id=principal.org_id).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        return _finding_view(row)

    @router.post("/v1/findings/{finding_id}/exceptions")
    def create_exception(
        finding_id: str,
        body: ExceptionRequest,
        session: Session = Depends(get_session),
        principal: Principal = Depends(editor),
    ) -> dict:
        finding = session.query(Finding).filter_by(id=finding_id, org_id=principal.org_id).one_or_none()
        if finding is None:
            raise HTTPException(status_code=404, detail="not found")
        row = RiskException(
            org_id=principal.org_id,
            finding_id=finding.id,
            reason=body.reason,
            approver=principal.subject,
            expires_at=body.expires_at,
        )
        session.add(row)
        session.flush()
        return {
            "id": row.id,
            "finding_id": finding.id,
            "reason": row.reason,
            "note": "exceptions do not change FAIL to PASS",
        }

    @router.get("/v1/runs/{run_id}/report")
    def get_report(
        run_id: str,
        format: str = Query("json"),
        session: Session = Depends(get_session),
        principal: Principal = Depends(viewer),
    ):
        row = _run(session, principal.org_id, run_id)
        attempts = session.query(Attempt).filter_by(org_id=principal.org_id, run_id=row.id).all()
        payload = {
            "run": _run_view(row, session),
            "attempts": [json.loads(item.result_json) for item in attempts],
            "limitations": [
                "This report is not a certification or a security score.",
                "Default export excludes raw prompts, traces, and target credentials.",
            ],
            "accepted_risks": [],
        }
        if format == "json":
            return payload
        summary = _report_summary(row, session, attempts)
        if format == "html":
            return Response(content=html_report(summary), media_type="text/html; charset=utf-8")
        if format == "junit":
            return Response(content=junit_report(summary), media_type="application/xml; charset=utf-8")
        if format == "pdf":
            return Response(
                content=pdf_report(summary),
                media_type="application/pdf",
                headers={"Content-Disposition": 'attachment; filename="report.pdf"'},
            )
        raise HTTPException(status_code=400, detail="unsupported report format")

    @router.get("/v1/projects/{project_id}/compare")
    def compare_runs(
        project_id: str,
        base: str = Query(...),
        head: str = Query(...),
        session: Session = Depends(get_session),
        principal: Principal = Depends(viewer),
    ) -> dict:
        _project(session, principal.org_id, project_id)
        base_run = _run(session, principal.org_id, base)
        head_run = _run(session, principal.org_id, head)
        if base_run.project_id != project_id or head_run.project_id != project_id:
            raise HTTPException(status_code=404, detail="not found")
        if base_run.suite_digest != head_run.suite_digest:
            return {
                "comparable": False,
                "reason": "comparison unavailable because suite manifests do not match",
            }
        base_map = _case_verdicts(session, base_run)
        head_map = _case_verdicts(session, head_run)
        new, persistent, gone, untested = [], [], [], []
        for case_id, verdict in head_map.items():
            if verdict == Verdict.FAIL and base_map.get(case_id) != Verdict.FAIL:
                new.append(case_id)
            elif verdict == Verdict.FAIL and base_map.get(case_id) == Verdict.FAIL:
                persistent.append(case_id)
            elif case_id in base_map and base_map[case_id] == Verdict.FAIL and verdict != Verdict.FAIL:
                gone.append(case_id)
        for case_id in base_map:
            if case_id not in head_map:
                untested.append(case_id)
        return {
            "comparable": True,
            "new": new,
            "persistent": persistent,
            "no_longer_observed": gone,
            "untested": untested,
            "copy": "not observed in this retest",
        }

    return router


def _project(session: Session, org_id: str, project_id: str) -> Project:
    row = session.query(Project).filter_by(id=project_id, org_id=org_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return row


def _run(session: Session, org_id: str, run_id: str) -> Run:
    row = session.query(Run).filter_by(id=run_id, org_id=org_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return row


def _project_view(row: Project) -> dict:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "name": row.name,
        "status": row.status,
        "export_mode": row.export_mode,
        "owner": row.owner_subject,
    }


def _env_view(row: Environment) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "local_alias": row.local_alias,
        "permitted_scope": json.loads(row.permitted_scope),
        "export_mode": row.export_mode,
    }


def _run_view(row: Run, session: Session) -> dict:
    count = session.query(Attempt).filter_by(org_id=row.org_id, run_id=row.id).count()
    return RunView(
        id=row.id,
        org_id=row.org_id,
        project_id=row.project_id,
        environment_id=row.environment_id,
        suite_digest=row.suite_digest,
        target_build=row.target_build,
        execution_status=ExecutionStatus(row.execution_status),
        gate=GateView(status=GateStatus(row.gate_status), reason=row.gate_reason),
        verdict_counts=json.loads(row.verdict_counts or "{}"),
        attempt_count=count,
        lease_epoch=row.lease_epoch,
        created_at=row.created_at,
    ).model_dump(mode="json")


def _finding_view(row: Finding) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "fingerprint": row.fingerprint,
        "case_id": row.case_id,
        "invariant": row.invariant,
        "severity": row.severity,
        "title": row.title,
        "first_seen_run_id": row.first_seen_run_id,
        "last_seen_run_id": row.last_seen_run_id,
        "disposition": row.disposition,
        "evidence_scope": row.evidence_scope,
        "fix_notes": "Retest the same case revision against the new build. A later PASS means not observed in this retest.",
    }


def _upsert_suite(session: Session, org_id: str, manifest: RunManifest) -> None:
    existing = session.query(SuiteVersion).filter_by(org_id=org_id, digest=manifest.suite_digest).one_or_none()
    if existing:
        return
    session.add(
        SuiteVersion(
            org_id=org_id,
            name=f"suite-{manifest.suite_digest}",
            digest=manifest.suite_digest,
            schema_version=manifest.suite_schema_version,
            case_inventory=json.dumps([item.model_dump() for item in manifest.cases]),
        )
    )


def _upsert_finding(session: Session, run: Run, case_id: str, reason_code: str, scope: str) -> None:
    fingerprint = f"{case_id}:{reason_code}"
    row = (
        session.query(Finding)
        .filter_by(org_id=run.org_id, project_id=run.project_id, fingerprint=fingerprint)
        .one_or_none()
    )
    if row:
        row.last_seen_run_id = run.id
        row.disposition = "open"
        return
    session.add(
        Finding(
            org_id=run.org_id,
            project_id=run.project_id,
            fingerprint=fingerprint,
            case_id=case_id,
            invariant=reason_code,
            severity="high",
            title=f"{case_id} {reason_code}",
            first_seen_run_id=run.id,
            last_seen_run_id=run.id,
            evidence_scope=scope,
        )
    )


def _apply_gate(run: Run, attempts: list[Attempt]) -> None:
    manifest = RunManifest.model_validate_json(run.manifest)
    by_case: dict[str, list[str]] = {}
    for attempt in attempts:
        by_case.setdefault(attempt.case_id, []).append(attempt.verdict)
    meta = {item.case_id: item for item in manifest.cases}
    cases = []
    counts = {item.value: 0 for item in Verdict}
    for case_id, verdicts in by_case.items():
        verdict = Verdict.FAIL if Verdict.FAIL in verdicts else Verdict(verdicts[-1])
        counts[verdict] = counts.get(verdict, 0) + 1
        inventory = meta.get(case_id)
        cases.append(
            {
                "case_id": case_id,
                "verdict": verdict,
                "required_for_gate": inventory.required_for_gate if inventory else True,
                "severity_if_violated": inventory.severity_if_violated if inventory else "high",
                "is_positive_control": inventory.is_positive_control if inventory else False,
            }
        )
    decision = evaluate_gate(setup_ok=True, cases=cases, policy=manifest.gate_policy)
    run.gate_status = decision.status
    run.gate_reason = decision.reason
    run.verdict_counts = json.dumps(counts)


def _case_verdicts(session: Session, run: Run) -> dict[str, str]:
    attempts = session.query(Attempt).filter_by(org_id=run.org_id, run_id=run.id).all()
    out: dict[str, str] = {}
    for attempt in attempts:
        if attempt.case_id not in out or attempt.verdict == Verdict.FAIL:
            out[attempt.case_id] = attempt.verdict
    return out


def _report_summary(row: Run, session: Session, attempts: list[Attempt]) -> RunSummary:
    parsed = [AttemptResult.model_validate(json.loads(item.result_json)) for item in attempts]
    env = session.query(Environment).filter_by(id=row.environment_id, org_id=row.org_id).one_or_none()
    manifest = RunManifest.model_validate(json.loads(row.manifest))
    meta = {item.case_id: item for item in manifest.cases}
    grouped: dict[str, list[AttemptResult]] = {}
    for item in parsed:
        grouped.setdefault(item.case_id, []).append(item)
    rollups: list[CaseRollup] = []
    for case_id, items in grouped.items():
        inventory = meta.get(case_id)
        failed = [item for item in items if item.verdict == Verdict.FAIL]
        valid = [item for item in items if item.verdict in {Verdict.PASS, Verdict.FAIL}]
        inconclusive = [item for item in items if item.verdict == Verdict.INCONCLUSIVE]
        errors = [item for item in items if item.verdict == Verdict.ERROR]
        skipped = [item for item in items if item.verdict == Verdict.SKIPPED]
        if failed:
            verdict = Verdict.FAIL
        elif inconclusive:
            verdict = Verdict.INCONCLUSIVE
        elif errors:
            verdict = Verdict.ERROR
        elif skipped and not valid:
            verdict = Verdict.SKIPPED
        else:
            verdict = Verdict.PASS
        rollups.append(
            CaseRollup(
                case_id=case_id,
                required_for_gate=inventory.required_for_gate if inventory else True,
                severity_if_violated=inventory.severity_if_violated if inventory else "high",
                verdict=verdict,
                failed_attempts=len(failed),
                valid_attempts=len(valid),
                inconclusive_attempts=len(inconclusive),
                error_attempts=len(errors),
                skipped_attempts=len(skipped),
            )
        )
    return RunSummary.model_validate(
        {
            "schema": "assure/summary/v1",
            "run_id": row.id,
            "project_id": row.project_id,
            "environment_alias": env.local_alias if env else row.environment_id,
            "target_build": row.target_build or "",
            "suite_digest": row.suite_digest,
            "started_at": row.created_at,
            "finished_at": row.created_at,
            "verdict_counts": json.loads(row.verdict_counts or "{}"),
            "cases": [item.model_dump() for item in rollups],
            "attempts": [item.model_dump(by_alias=True) for item in parsed],
            "gate_status": row.gate_status,
            "gate_reason": row.gate_reason,
            "cleanup_ok": row.cleanup_ok,
        }
    )


# imported for type checkers
_ = (datetime, timezone, WorkItem)
