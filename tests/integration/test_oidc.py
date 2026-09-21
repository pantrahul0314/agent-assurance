from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from assure_control_api.app import create_app
from assure_control_api.db import make_engine, make_session_factory
from assure_control_api.ids import ENV_A
from assure_control_api.oidc import GITHUB_ISSUER, OidcSettings


def _rsa_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    jwk["kid"] = "test-key"
    return key, {"keys": [jwk]}


def _client(ci_jwks=None, oidc=None, claim_loader=None) -> TestClient:
    engine = make_engine("sqlite://")
    factory = make_session_factory(engine)
    return TestClient(
        create_app(engine, factory, oidc=oidc, ci_jwks=ci_jwks, oidc_claim_loader=claim_loader)
    )


def test_api_key_still_works() -> None:
    client = _client()
    response = client.get("/v1/me", headers={"Authorization": "Bearer org-a-editor-token"})
    assert response.status_code == 200
    assert response.json()["subject"] == "editor-a"


def test_oidc_callback_establishes_session() -> None:
    settings = OidcSettings(
        issuer="https://issuer.example",
        client_id="assure-web",
        redirect_url="http://127.0.0.1:8000/v1/auth/oidc/callback",
    )
    settings.pending_states["state-1"] = "verifier"

    def loader(_settings, code: str) -> dict:
        assert code == "good-code"
        return {"sub": "oidc-editor-a", "iss": settings.issuer}

    client = _client(oidc=settings, claim_loader=loader)
    response = client.get("/v1/auth/oidc/callback?code=good-code&state=state-1", follow_redirects=False)
    assert response.status_code == 302
    me = client.get("/v1/me")
    assert me.status_code == 200
    assert me.json()["subject"] == "oidc-editor-a"
    assert me.json()["org_id"] == "11111111-1111-1111-1111-111111111111"


def test_github_exchange_accepts_valid_claims() -> None:
    key, jwks = _rsa_pair()
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "iss": GITHUB_ISSUER,
            "aud": "assure-ci",
            "sub": "repo:acme/support:environment:staging",
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "iat": int(now.timestamp()),
            "repository": "acme/support",
            "job_workflow_ref": "acme/support/.github/workflows/assure.yml@refs/heads/main",
            "event_name": "push",
            "environment": "staging",
        },
        key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    client = _client(ci_jwks=jwks)
    response = client.post("/v1/ci/oidc/exchange", json={"jwt": token, "environment_id": ENV_A})
    assert response.status_code == 200, response.text
    minted = response.json()["token"]
    me = client.get("/v1/me", headers={"Authorization": f"Bearer {minted}"})
    assert me.status_code == 200
    assert me.json()["role"] == "runner"


def test_github_exchange_rejects_bad_claims() -> None:
    key, jwks = _rsa_pair()
    now = datetime.now(timezone.utc)
    client = _client(ci_jwks=jwks)
    base = {
        "iss": GITHUB_ISSUER,
        "aud": "assure-ci",
        "sub": "repo:acme/support:ref:refs/heads/main",
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "iat": int(now.timestamp()),
        "repository": "acme/support",
        "job_workflow_ref": "acme/support/.github/workflows/assure.yml@refs/heads/main",
        "event_name": "push",
        "environment": "staging",
    }
    expired = {**base, "exp": int((now - timedelta(minutes=5)).timestamp())}
    fork_pr = {**base, "event_name": "pull_request", "repository": "evil/support"}
    wrong_aud = {**base, "aud": "someone-else"}
    wrong_repo = {**base, "repository": "evil/support"}
    for claims in (expired, fork_pr, wrong_aud, wrong_repo):
        token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})
        response = client.post("/v1/ci/oidc/exchange", json={"jwt": token})
        assert response.status_code == 401, claims
