from __future__ import annotations

import json

from sqlalchemy.orm import Session

from assure_control_api.auth import hash_token
from assure_control_api.ids import ENV_A, ENV_B, ORG_A, ORG_B, PROJECT_A, PROJECT_B
from assure_control_api.models import (
    ApiCredential,
    Environment,
    Membership,
    Organization,
    Project,
)
from assure_control_api.oidc import seed_github_trust


SEED_TOKENS = {
    "org-a-editor-token": (ORG_A, "editor-a", "editor", None),
    "org-a-viewer-token": (ORG_A, "viewer-a", "viewer", None),
    "org-a-runner-token": (ORG_A, "runner-a", "runner", ENV_A),
    "org-b-editor-token": (ORG_B, "editor-b", "editor", None),
    "org-b-runner-token": (ORG_B, "runner-b", "runner", ENV_B),
}


def seed_if_empty(session: Session) -> None:
    if session.query(Organization).first() is not None:
        return
    session.add_all(
        [
            Organization(id=ORG_A, name="Acme Support"),
            Organization(id=ORG_B, name="Other Corp"),
            Membership(org_id=ORG_A, subject="editor-a", role="editor"),
            Membership(org_id=ORG_A, subject="oidc-editor-a", role="editor"),
            Membership(org_id=ORG_A, subject="viewer-a", role="viewer"),
            Membership(org_id=ORG_A, subject="runner-a", role="runner"),
            Membership(org_id=ORG_B, subject="editor-b", role="editor"),
            Membership(org_id=ORG_B, subject="runner-b", role="runner"),
            Project(id=PROJECT_A, org_id=ORG_A, name="Support assistant", owner_subject="editor-a"),
            Project(id=PROJECT_B, org_id=ORG_B, name="Other assistant", owner_subject="editor-b"),
            Environment(
                id=ENV_A,
                org_id=ORG_A,
                project_id=PROJECT_A,
                local_alias="support_staging",
                permitted_scope=json.dumps(["prepare_support_two_tenants", "cleanup_namespace"]),
            ),
            Environment(
                id=ENV_B,
                org_id=ORG_B,
                project_id=PROJECT_B,
                local_alias="support_staging",
                permitted_scope=json.dumps(["prepare_support_two_tenants", "cleanup_namespace"]),
            ),
        ]
    )
    for token, (org_id, subject, role, environment_id) in SEED_TOKENS.items():
        session.add(
            ApiCredential(
                org_id=org_id,
                token_hash=hash_token(token),
                subject=subject,
                role=role,
                environment_id=environment_id,
            )
        )
    seed_github_trust(session)
    session.flush()
