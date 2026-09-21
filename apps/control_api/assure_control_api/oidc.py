from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import jwt
from jwt import PyJWKClient
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from assure_control_api.auth import Principal, hash_token
from assure_control_api.ids import ENV_A, ORG_A
from assure_control_api.models import ApiCredential, AuthSession, Membership, OidcTrustPolicy, new_id, utcnow

GITHUB_ISSUER = "https://token.actions.githubusercontent.com"
SESSION_COOKIE = "assure_session"
SESSION_HOURS = 8
RUNNER_TOKEN_MINUTES = 30


@dataclass
class OidcSettings:
    issuer: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    redirect_url: str = "http://127.0.0.1:8000/v1/auth/oidc/callback"
    audience: str | None = None
    jwks: dict[str, Any] | None = None
    token_endpoint: str | None = None
    authorization_endpoint: str | None = None
    pending_states: dict[str, str] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        return bool(self.issuer and self.client_id)

    @classmethod
    def from_env(cls) -> OidcSettings:
        issuer = os.environ.get("OIDC_ISSUER")
        return cls(
            issuer=issuer,
            client_id=os.environ.get("OIDC_CLIENT_ID"),
            client_secret=os.environ.get("OIDC_CLIENT_SECRET"),
            redirect_url=os.environ.get("OIDC_REDIRECT_URL", "http://127.0.0.1:8000/v1/auth/oidc/callback"),
            audience=os.environ.get("OIDC_AUDIENCE"),
            token_endpoint=os.environ.get("OIDC_TOKEN_ENDPOINT"),
            authorization_endpoint=os.environ.get("OIDC_AUTHORIZATION_ENDPOINT"),
        )


class GithubExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    jwt: str
    environment_id: str | None = None


def login_redirect(settings: OidcSettings) -> str:
    if not settings.enabled or not settings.issuer:
        raise ValueError("OIDC is not configured")
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(32)
    settings.pending_states[state] = verifier
    authorize = settings.authorization_endpoint or f"{settings.issuer.rstrip('/')}/authorize"
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.client_id,
            "redirect_uri": settings.redirect_url,
            "scope": "openid profile email",
            "state": state,
            "code_challenge": verifier,
            "code_challenge_method": "plain",
        }
    )
    return f"{authorize}?{query}"


def decode_id_token(settings: OidcSettings, token: str) -> dict[str, Any]:
    if not settings.issuer:
        raise ValueError("OIDC is not configured")
    audience = settings.audience or settings.client_id
    options = {"require": ["exp", "iss", "sub"], "verify_aud": bool(audience)}
    if settings.jwks:
        return jwt.decode(
            token,
            key=_key_from_jwks(settings.jwks, token),
            algorithms=["RS256"],
            audience=audience,
            issuer=settings.issuer,
            options=options,
        )
    jwks_url = f"{settings.issuer.rstrip('/')}/.well-known/jwks.json"
    client = PyJWKClient(jwks_url)
    signing_key = client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=audience,
        issuer=settings.issuer,
        options=options,
    )


def establish_session(db: Session, claims: dict[str, Any]) -> AuthSession:
    subject = str(claims.get("sub") or "")
    email = str(claims.get("email") or "")
    membership = db.query(Membership).filter(Membership.subject.in_([subject, email])).first()
    if membership is None:
        raise LookupError("no membership for OIDC subject")
    row = AuthSession(
        org_id=membership.org_id,
        subject=membership.subject,
        role=membership.role,
        expires_at=utcnow() + timedelta(hours=SESSION_HOURS),
    )
    db.add(row)
    db.flush()
    return row


def decode_ci_jwt(token: str, *, issuer: str, audience: str, jwks: dict[str, Any] | None = None) -> dict[str, Any]:
    if jwks:
        return jwt.decode(
            token,
            key=_key_from_jwks(jwks, token),
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
        )
    client = PyJWKClient(f"{issuer.rstrip('/')}/.well-known/jwks.json")
    signing_key = client.get_signing_key_from_jwt(token)
    return jwt.decode(token, signing_key.key, algorithms=["RS256"], audience=audience, issuer=issuer)


def exchange_github_oidc(
    db: Session,
    token: str,
    *,
    jwks: dict[str, Any] | None = None,
    environment_id: str | None = None,
) -> tuple[str, Principal]:
    unverified = jwt.decode(token, options={"verify_signature": False})
    issuer = str(unverified.get("iss") or GITHUB_ISSUER)
    policies = db.query(OidcTrustPolicy).filter_by(issuer=issuer, revoked=False).all()
    if not policies:
        raise PermissionError("no trust policy for issuer")
    last_error = "token rejected"
    for policy in policies:
        try:
            claims = decode_ci_jwt(token, issuer=policy.issuer, audience=policy.audience, jwks=jwks)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            continue
        if not _ci_claims_allowed(claims, policy):
            last_error = "claims do not match trust policy"
            continue
        env_id = environment_id or policy.environment_id
        raw = f"oidc-{new_id()}"
        cred = ApiCredential(
            org_id=policy.org_id,
            token_hash=hash_token(raw),
            subject=str(claims.get("sub") or "github-actions"),
            role="runner",
            environment_id=env_id,
            expires_at=utcnow() + timedelta(minutes=RUNNER_TOKEN_MINUTES),
        )
        db.add(cred)
        db.flush()
        return raw, Principal(policy.org_id, cred.subject, cred.role, cred.environment_id, cred.id)
    raise PermissionError(last_error)


def _ci_claims_allowed(claims: dict[str, Any], policy: OidcTrustPolicy) -> bool:
    event = str(claims.get("event_name") or "")
    if event in {"pull_request", "pull_request_target"}:
        return False
    if str(claims.get("repository") or "") != policy.repository:
        return False
    workflow = str(claims.get("job_workflow_ref") or claims.get("workflow_ref") or "")
    if policy.workflow_ref not in workflow and workflow != policy.workflow_ref:
        return False
    if policy.github_environment and str(claims.get("environment") or "") != policy.github_environment:
        return False
    exp = claims.get("exp")
    if exp is None:
        return False
    exp_dt = datetime.fromtimestamp(int(exp), tz=timezone.utc)
    return exp_dt > utcnow()


def _key_from_jwks(jwks: dict[str, Any], token: str):
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    for item in jwks.get("keys", []):
        if kid is None or item.get("kid") == kid:
            return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(item))
    raise ValueError("no matching jwk")


def seed_github_trust(session: Session) -> None:
    if session.query(OidcTrustPolicy).first() is not None:
        return
    session.add(
        OidcTrustPolicy(
            org_id=ORG_A,
            issuer=GITHUB_ISSUER,
            audience="assure-ci",
            repository="acme/support",
            workflow_ref="acme/support/.github/workflows/assure.yml",
            github_environment="staging",
            environment_id=ENV_A,
        )
    )
