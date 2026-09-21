from __future__ import annotations

import os
from collections.abc import Callable

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import sessionmaker

from assure_control_api.auth import bind_auth
from assure_control_api.db import init_db, make_engine, make_session_factory, session_dep
from assure_control_api.oidc import OidcSettings, decode_id_token
from assure_control_api.rls import apply_rls, set_auth_lookup
from assure_control_api.routes import build_router
from assure_control_api.seed import seed_if_empty


def default_oidc_claim_loader(settings: OidcSettings, code: str) -> dict:
    token_url = settings.token_endpoint or f"{(settings.issuer or '').rstrip('/')}/oauth/token"
    response = httpx.post(
        token_url,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.redirect_url,
            "client_id": settings.client_id,
            "client_secret": settings.client_secret or "",
        },
        timeout=15.0,
    )
    response.raise_for_status()
    return decode_id_token(settings, response.json()["id_token"])


def create_app(
    engine=None,
    session_factory: sessionmaker | None = None,
    oidc: OidcSettings | None = None,
    ci_jwks: dict | None = None,
    oidc_claim_loader: Callable | None = None,
) -> FastAPI:
    engine = engine or make_engine()
    session_factory = session_factory or make_session_factory(engine)
    if os.environ.get("ASSURE_RUN_MIGRATIONS", "1") == "1":
        init_db(engine)
        apply_rls(engine)
        with session_factory() as session:
            set_auth_lookup(session, True)
            seed_if_empty(session)
            session.commit()

    app = FastAPI(title="Assure Control API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:3000", "http://web:5173"],
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    get_session = session_dep(session_factory)
    get_principal = bind_auth(get_session)
    app.include_router(build_router(get_session, get_principal))
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.oidc = oidc or OidcSettings.from_env()
    app.state.ci_jwks = ci_jwks
    app.state.oidc_claim_loader = oidc_claim_loader or default_oidc_claim_loader

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
