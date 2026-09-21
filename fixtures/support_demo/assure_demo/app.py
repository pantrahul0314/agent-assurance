from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from assure_contracts.adapters import (
    ApprovedFixtureChange,
    ApprovedScope,
    AttemptContext,
    CleanupResult,
    Receipt,
    ConversationResult,
    EvidenceEnvelope,
    FixtureHandle,
    FixtureSpecRequest,
    FixtureState,
    ObservationCursor,
    PreflightResult,
    ScenarioRequest,
    StateSnapshot,
    TargetBuild,
)
from assure_contracts.enums import TargetMode

from assure_demo.agent import route_and_execute
from assure_demo.store import DemoStore


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatRequest(StrictModel):
    session_id: str
    message: str
    correlation_id: str
    max_turns: int = 4


class ObserverToggle(StrictModel):
    enabled: bool


class PrepareRequest(FixtureSpecRequest):
    fail_cleanup: bool = False


def create_app(store: DemoStore | None = None) -> FastAPI:
    store = store or DemoStore()
    app = FastAPI(title="Assure Support Demo", version="0.1.0")
    app.state.store = store

    def _user(authorization: str | None) -> tuple[str, object]:
        token = _bearer(authorization)
        principal = store.principal_for(token)
        if principal is None:
            raise HTTPException(status_code=401, detail="unknown principal")
        return token, principal

    def _admin(authorization: str | None) -> None:
        token = _bearer(authorization)
        if token != store.admin_token():
            raise HTTPException(status_code=401, detail="admin credentials required")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/chat", response_model=ConversationResult)
    def chat(body: ChatRequest, authorization: str | None = Header(default=None)) -> ConversationResult:
        _token, principal = _user(authorization)
        request = ScenarioRequest(
            credential_ref=principal.subject,
            session_id=body.session_id,
            input_text=body.message,
            correlation_id=body.correlation_id,
            max_turns=body.max_turns,
        )
        _ = request
        return route_and_execute(store, principal, body.message, body.correlation_id, session_id=body.session_id)

    @app.get("/admin/build", response_model=TargetBuild)
    def build(authorization: str | None = Header(default=None)) -> TargetBuild:
        _admin(authorization)
        return TargetBuild(build_id=store.build_id, mode=store.mode)

    @app.post("/admin/preflight", response_model=PreflightResult)
    def preflight(scope: ApprovedScope, authorization: str | None = Header(default=None)) -> PreflightResult:
        _admin(authorization)
        errors: list[str] = []
        if scope.target_alias != "support_staging":
            errors.append("unauthorized target alias")
        if scope.fixture_profile != "support_two_tenants":
            errors.append("unsupported fixture profile")
        return PreflightResult(
            ok=not errors,
            build=TargetBuild(build_id=store.build_id, mode=store.mode),
            principals=[p.subject for p in store.principals.values()],
            fixture_access=True,
            observation_available=store.observer_enabled,
            cleanup_available=True,
            errors=errors,
        )

    @app.post("/admin/fixtures/prepare", response_model=FixtureHandle)
    def prepare(body: PrepareRequest, authorization: str | None = Header(default=None)) -> FixtureHandle:
        _admin(authorization)
        try:
            state = store.prepare(body.namespace, fail_cleanup=body.fail_cleanup)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return FixtureHandle(
            namespace=body.namespace,
            profile=body.profile,
            bindings=state.bindings,
            canaries=state.canaries,
            resource_ids=state.resource_ids,
        )

    @app.post("/admin/fixtures/verify", response_model=FixtureState)
    def verify(handle: FixtureHandle, authorization: str | None = Header(default=None)) -> FixtureState:
        _admin(authorization)
        state = store.get_namespace(handle.namespace)
        if state is None:
            return FixtureState(namespace=handle.namespace, exists=False)
        return FixtureState(
            namespace=handle.namespace,
            exists=True,
            quarantined=state.quarantined,
            tickets={ref: ticket.ticket_id for ref, ticket in ((t.ref, t) for t in state.tickets.values())},
        )

    @app.post("/admin/fixtures/change", response_model=Receipt)
    def apply_change(body: ApprovedFixtureChange, authorization: str | None = Header(default=None)) -> Receipt:
        _admin(authorization)
        try:
            detail = store.apply_change(
                body.kind,
                body.namespace,
                body.payload.get("resource_ref"),
                body.payload.get("subject"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Receipt(accepted=True, detail=detail)

    @app.post("/admin/fixtures/cleanup", response_model=CleanupResult)
    def cleanup(handle: FixtureHandle, authorization: str | None = Header(default=None)) -> CleanupResult:
        _admin(authorization)
        ok, quarantined, detail = store.cleanup(handle.namespace)
        return CleanupResult(ok=ok, namespace=handle.namespace, quarantined=quarantined, detail=detail)

    @app.post("/admin/observations/begin", response_model=ObservationCursor)
    def begin(context: AttemptContext, authorization: str | None = Header(default=None)) -> ObservationCursor:
        _admin(authorization)
        return ObservationCursor(
            attempt_id=context.attempt_id,
            correlation_id=context.correlation_id,
            started_at=datetime.now(timezone.utc),
            start_sequence=store.next_sequence(),
            disabled=not store.observer_enabled,
            declared_sources=context.declared_sources,
        )

    @app.post("/admin/observations/finish", response_model=EvidenceEnvelope)
    def finish(cursor: ObservationCursor, authorization: str | None = Header(default=None)) -> EvidenceEnvelope:
        _admin(authorization)
        expected = cursor.declared_sources or ["retrieval_returns", "response_capture", "tool_audit"]
        if cursor.disabled or not store.observer_enabled:
            now = datetime.now(timezone.utc)
            return EvidenceEnvelope(
                expected_sources=expected,
                observed_sources=[],
                sequence_start=cursor.start_sequence,
                sequence_end=cursor.start_sequence,
                completion_status="unavailable",
                observation_started_at=cursor.started_at,
                observation_finished_at=now,
                receipt=False,
            )
        events = store.events_since(cursor.start_sequence, cursor.correlation_id)
        sources = sorted({event.source for event in events})
        complete = all(source in sources for source in expected)
        now = datetime.now(timezone.utc)
        return EvidenceEnvelope(
            expected_sources=expected,
            observed_sources=sources,
            sequence_start=cursor.start_sequence,
            sequence_end=events[-1].sequence if events else cursor.start_sequence,
            completion_status="complete" if complete else "incomplete",
            observation_started_at=cursor.started_at,
            observation_finished_at=now,
            facts=[event.fact for event in events],
            events=events,
            receipt=complete,
        )

    @app.get("/admin/state/{namespace}", response_model=StateSnapshot)
    def snapshot(namespace: str, authorization: str | None = Header(default=None)) -> StateSnapshot:
        _admin(authorization)
        state = store.get_namespace(namespace)
        tickets = {}
        if state:
            tickets = {
                ticket.ticket_id: {
                    "tenant": ticket.tenant,
                    "status": ticket.status,
                    "ref": ticket.ref,
                    "escalated": "true" if ticket.ticket_id in store.escalations else "false",
                }
                for ticket in state.tickets.values()
            }
        return StateSnapshot(namespace=namespace, tickets=tickets, captured_at=datetime.now(timezone.utc))

    @app.post("/admin/observer")
    def toggle_observer(body: ObserverToggle, authorization: str | None = Header(default=None)) -> dict[str, bool]:
        _admin(authorization)
        store.observer_enabled = body.enabled
        return {"enabled": store.observer_enabled}

    class ModeBody(StrictModel):
        mode: TargetMode

    @app.post("/admin/mode")
    def set_mode(body: ModeBody, authorization: str | None = Header(default=None)) -> dict[str, str]:
        _admin(authorization)
        store.mode = body.mode
        return {"mode": store.mode}

    return app


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return authorization.removeprefix("Bearer ").strip()
