from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    data_region: Mapped[str] = mapped_column(String(64), default="local")
    retention_days: Mapped[int] = mapped_column(Integer, default=90)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "subject"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32))


class ApiCredential(Base):
    __tablename__ = "api_credentials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    subject: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32))
    environment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        UniqueConstraint("org_id", "id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(200))
    owner_subject: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default="active")
    export_mode: Mapped[str] = mapped_column(String(32), default="summary")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Environment(Base):
    __tablename__ = "environments"
    __table_args__ = (
        ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        ForeignKeyConstraint(["org_id", "project_id"], ["projects.org_id", "projects.id"]),
        UniqueConstraint("org_id", "id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    local_alias: Mapped[str] = mapped_column(String(100))
    permitted_scope: Mapped[str] = mapped_column(Text, default="[]")
    export_mode: Mapped[str] = mapped_column(String(32), default="summary")


class SuiteVersion(Base):
    __tablename__ = "suite_versions"
    __table_args__ = (UniqueConstraint("org_id", "digest"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(200))
    digest: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(64), default="assure/v1")
    case_inventory: Mapped[str] = mapped_column(Text, default="[]")
    approved: Mapped[bool] = mapped_column(Boolean, default=True)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("org_id", "idempotency_key"),
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(["org_id", "project_id"], ["projects.org_id", "projects.id"]),
        ForeignKeyConstraint(["org_id", "environment_id"], ["environments.org_id", "environments.id"]),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    environment_id: Mapped[str] = mapped_column(String(36), index=True)
    suite_digest: Mapped[str] = mapped_column(String(64))
    manifest: Mapped[str] = mapped_column(Text)
    target_build: Mapped[str | None] = mapped_column(String(200), nullable=True)
    execution_status: Mapped[str] = mapped_column(String(32), default="Registered")
    gate_status: Mapped[str] = mapped_column(String(32), default="not_evaluated")
    gate_reason: Mapped[str] = mapped_column(Text, default="")
    lease_epoch: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    verdict_counts: Mapped[str] = mapped_column(Text, default="{}")
    cleanup_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        UniqueConstraint("org_id", "run_id", "attempt_id"),
        ForeignKeyConstraint(["org_id", "run_id"], ["runs.org_id", "runs.id"]),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    attempt_id: Mapped[str] = mapped_column(String(128))
    case_id: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    variant: Mapped[str] = mapped_column(String(64), default="default")
    repetition: Mapped[int] = mapped_column(Integer, default=1)
    fixture_namespace: Mapped[str | None] = mapped_column(String(200), nullable=True)
    verdict: Mapped[str] = mapped_column(String(32))
    evidence_status: Mapped[str] = mapped_column(String(32))
    result_json: Mapped[str] = mapped_column(Text)
    content_digest: Mapped[str] = mapped_column(String(64))
    sequence: Mapped[int] = mapped_column(Integer, default=1)


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (UniqueConstraint("org_id", "project_id", "fingerprint"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    fingerprint: Mapped[str] = mapped_column(String(200))
    case_id: Mapped[str] = mapped_column(String(64))
    invariant: Mapped[str] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(300))
    first_seen_run_id: Mapped[str] = mapped_column(String(36))
    last_seen_run_id: Mapped[str] = mapped_column(String(36))
    disposition: Mapped[str] = mapped_column(String(64), default="open")
    evidence_scope: Mapped[str] = mapped_column(String(128), default="retrieval_and_output")


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    object_key: Mapped[str] = mapped_column(String(400))
    content_digest: Mapped[str] = mapped_column(String(64))
    export_mode: Mapped[str] = mapped_column(String(32), default="summary")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    actor: Mapped[str] = mapped_column(String(200))
    event: Mapped[str] = mapped_column(String(100))
    object_ref: Mapped[str] = mapped_column(String(200))
    request_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkItem(Base):
    __tablename__ = "work_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    object_ref: Mapped[str] = mapped_column(String(200))
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_epoch: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32))
    environment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OidcTrustPolicy(Base):
    __tablename__ = "oidc_trust_policies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    issuer: Mapped[str] = mapped_column(String(300))
    audience: Mapped[str] = mapped_column(String(300))
    repository: Mapped[str] = mapped_column(String(200))
    workflow_ref: Mapped[str] = mapped_column(String(400))
    github_environment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    environment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class RiskException(Base):
    __tablename__ = "risk_exceptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    finding_id: Mapped[str] = mapped_column(String(36))
    reason: Mapped[str] = mapped_column(Text)
    approver: Mapped[str] = mapped_column(String(200))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
