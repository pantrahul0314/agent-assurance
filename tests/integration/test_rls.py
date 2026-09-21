from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from assure_control_api.app import create_app
from assure_control_api.db import make_engine, make_session_factory
from assure_control_api.ids import ORG_A, ORG_B
from assure_control_api.models import Project
from assure_control_api.rls import is_postgres, set_auth_lookup, set_org_context


@pytest.mark.skipif(not os.environ.get("ASSURE_RLS_TEST_URL"), reason="Postgres RLS test URL not configured")
def test_rls_hides_rows_without_org_context() -> None:
    url = os.environ["ASSURE_RLS_TEST_URL"]
    engine = make_engine(url)
    if not is_postgres(engine):
        pytest.skip("not postgres")
    factory = make_session_factory(engine)
    create_app(engine, factory)
    with factory() as session:
        set_auth_lookup(session, False)
        set_org_context(session, "")
        assert session.query(Project).count() == 0
        set_org_context(session, ORG_A)
        assert session.query(Project).filter_by(org_id=ORG_B).count() == 0
        set_org_context(session, ORG_B)
        rows = session.execute(text("SELECT org_id FROM projects")).fetchall()
        assert all(row[0] == ORG_B for row in rows)
