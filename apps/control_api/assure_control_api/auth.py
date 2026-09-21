from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from assure_control_api.models import ApiCredential, AuthSession
from assure_control_api.rls import set_auth_lookup, set_org_context


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@dataclass
class Principal:
    org_id: str
    subject: str
    role: str
    environment_id: str | None
    credential_id: str


def get_principal(
    session: Session,
    authorization: str | None,
    cookie_session: str | None = None,
) -> Principal:
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        cred = session.query(ApiCredential).filter_by(token_hash=hash_token(token), revoked=False).one_or_none()
        if cred is not None:
            if cred.expires_at and _as_utc(cred.expires_at) <= datetime.now(timezone.utc):
                raise HTTPException(status_code=401, detail="expired token")
            return Principal(cred.org_id, cred.subject, cred.role, cred.environment_id, cred.id)
    if cookie_session:
        row = session.query(AuthSession).filter_by(id=cookie_session).one_or_none()
        if row is not None and _as_utc(row.expires_at) > datetime.now(timezone.utc):
            return Principal(row.org_id, row.subject, row.role, row.environment_id, row.id)
    raise HTTPException(status_code=401, detail="missing bearer token")


def require_roles(*roles: str):
    def _inner(principal: Principal) -> Principal:
        if principal.role not in roles:
            raise HTTPException(status_code=403, detail="insufficient role")
        return principal

    return _inner


def scoped_or_404(principal: Principal, org_id: str) -> None:
    if principal.org_id != org_id:
        raise HTTPException(status_code=404, detail="not found")


def bind_auth(get_session):
    def _dep(
        request: Request,
        session: Session = Depends(get_session),
        authorization: str | None = Header(default=None),
    ) -> Principal:
        principal = get_principal(session, authorization, request.cookies.get("assure_session"))
        set_auth_lookup(session, False)
        set_org_context(session, principal.org_id)
        return principal

    return _dep
