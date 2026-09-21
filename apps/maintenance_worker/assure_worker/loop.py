from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from assure_contracts.enums import ExecutionStatus, GateStatus
from assure_control_api.models import Artifact, Run, WorkItem, new_id, utcnow
from assure_control_api.rls import set_auth_lookup, set_org_context


def reap_once(session: Session, epoch: int) -> int:
    set_auth_lookup(session, True)
    set_org_context(session, "")
    now = utcnow()
    changed = 0
    stale = (
        session.query(Run)
        .filter(
            Run.execution_status.in_([ExecutionStatus.RUNNING, ExecutionStatus.UPLOADING]),
            Run.lease_expires_at.is_not(None),
            Run.lease_expires_at < now,
        )
        .all()
    )
    for run in stale:
        set_org_context(session, run.org_id)
        set_auth_lookup(session, False)
        run.execution_status = ExecutionStatus.INCOMPLETE
        run.gate_status = GateStatus.BLOCKED_INCOMPLETE
        run.gate_reason = "runner lease expired; execution state unknown"
        session.add(
            WorkItem(
                org_id=run.org_id,
                kind="reap_stale_run",
                object_ref=run.id,
                lease_token=new_id(),
                lease_epoch=epoch,
                done=True,
            )
        )
        changed += 1
        set_auth_lookup(session, True)
        set_org_context(session, "")

    expired = session.query(Artifact).filter(Artifact.deleted.is_(False), Artifact.expires_at.is_not(None), Artifact.expires_at < now).all()
    for artifact in expired:
        set_org_context(session, artifact.org_id)
        set_auth_lookup(session, False)
        artifact.deleted = True
        changed += 1
        set_auth_lookup(session, True)
        set_org_context(session, "")
    return changed


def sleep_interval() -> float:
    return 5.0


def lease_window() -> timedelta:
    return timedelta(minutes=15)
