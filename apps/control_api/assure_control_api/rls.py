from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from assure_control_api.models import Base

ORG_SETTING = "assure.org_id"
AUTH_SETTING = "assure.auth_lookup"

CUSTOMER_TABLES = [
    "organizations",
    "memberships",
    "api_credentials",
    "projects",
    "environments",
    "suite_versions",
    "runs",
    "attempts",
    "findings",
    "artifacts",
    "audit_events",
    "work_items",
    "risk_exceptions",
    "auth_sessions",
    "oidc_trust_policies",
]


def is_postgres(engine: Engine) -> bool:
    return engine.dialect.name == "postgresql"


def apply_rls(engine: Engine) -> None:
    if not is_postgres(engine):
        return
    statements = []
    for table in CUSTOMER_TABLES:
        column = "id" if table == "organizations" else "org_id"
        statements.append(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        statements.append(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        statements.append(f'DROP POLICY IF EXISTS assure_org_isolation ON "{table}"')
        statements.append(
            f"""
            CREATE POLICY assure_org_isolation ON "{table}"
            USING (
                current_setting('{AUTH_SETTING}', true) = '1'
                OR {column} = current_setting('{ORG_SETTING}', true)
            )
            WITH CHECK (
                current_setting('{AUTH_SETTING}', true) = '1'
                OR {column} = current_setting('{ORG_SETTING}', true)
            )
            """
        )
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
        try:
            conn.execute(text("GRANT USAGE ON SCHEMA public TO assure_app"))
            conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO assure_app"))
            conn.execute(text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO assure_app"))
        except Exception:
            pass
        _ = Base.metadata


def set_auth_lookup(session, enabled: bool) -> None:
    engine = session.get_bind()
    if not is_postgres(engine):
        return
    value = "1" if enabled else ""
    session.execute(text(f"SELECT set_config('{AUTH_SETTING}', :v, true)"), {"v": value})


def set_org_context(session, org_id: str | None) -> None:
    engine = session.get_bind()
    if not is_postgres(engine):
        return
    session.execute(text(f"SELECT set_config('{ORG_SETTING}', :v, true)"), {"v": org_id or ""})
