from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from assure_contracts.api import AttemptBatchItem, AttemptBatchRequest, CompleteRunRequest, CreateRunRequest
from assure_contracts.manifest import RunManifest, SuiteInventory
from assure_contracts.result import AttemptResult
from assure_control_api.app import create_app
from assure_control_api.db import make_engine, make_session_factory
from assure_control_api.ids import ENV_A, ENV_B, PROJECT_A
from assure_control_api.models import Run
from assure_worker.loop import reap_once


def _client() -> TestClient:
    engine = make_engine("sqlite://")
    factory = make_session_factory(engine)
    return TestClient(create_app(engine, factory))


def _manifest(run_id: str = "run-local") -> RunManifest:
    return RunManifest.model_validate(
        {
            "schema": "assure/manifest/v1",
            "run_id": run_id,
            "environment_alias": "support_staging",
            "suite_digest": "digest-support-v1",
            "cases": [
                SuiteInventory(
                    case_id="POS-01",
                    revision=1,
                    required_for_gate=True,
                    repetitions=1,
                    severity_if_violated="high",
                    is_positive_control=True,
                ).model_dump(),
                SuiteInventory(
                    case_id="TEN-01",
                    revision=1,
                    required_for_gate=True,
                    repetitions=1,
                    severity_if_violated="high",
                ).model_dump(),
            ],
            "target_alias": "support_staging",
            "target_build": "demo-support-local",
            "fixture_profile": "support_two_tenants",
        }
    )


def _attempt(case_id: str, verdict: str, reason: str) -> AttemptResult:
    return AttemptResult.model_validate(
        {
            "schema": "assure/result/v1",
            "case_id": case_id,
            "attempt_id": f"{case_id}-1",
            "verdict": verdict,
            "reason_code": reason,
            "assertions": [],
            "evidence_complete": verdict != "INCONCLUSIVE",
            "target_build": "demo-support-local",
        }
    )


def _register(client: TestClient, token: str, key: str, env_id: str = ENV_A) -> str:
    body = CreateRunRequest(
        environment_id=env_id,
        suite_id="digest-support-v1",
        manifest=_manifest(key),
        idempotency_key=key,
    )
    response = client.post(
        "/v1/runs",
        headers={"Authorization": f"Bearer {token}"},
        json=body.model_dump(mode="json", by_alias=True),
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_cross_org_access_is_denied() -> None:
    client = _client()
    run_id = _register(client, "org-a-runner-token", "iso-1")
    denied = client.get(f"/v1/runs/{run_id}", headers={"Authorization": "Bearer org-b-editor-token"})
    assert denied.status_code == 404
    findings = client.get(
        f"/v1/projects/{PROJECT_A}/findings",
        headers={"Authorization": "Bearer org-b-editor-token"},
    )
    assert findings.status_code == 404


def test_duplicate_attempt_accepted_conflict_rejected() -> None:
    client = _client()
    run_id = _register(client, "org-a-runner-token", "dup-1")
    headers = {"Authorization": "Bearer org-a-runner-token"}
    client.post(f"/v1/runs/{run_id}/claim", headers=headers)
    result = _attempt("TEN-01", "FAIL", "FORBIDDEN_RESOURCE_RETURNED")
    payload = result.model_dump(mode="json", by_alias=True)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    batch = AttemptBatchRequest(
        items=[AttemptBatchItem(attempt_id=result.attempt_id, sequence=1, content_digest=digest, result=result)]
    )
    first = client.post(
        f"/v1/runs/{run_id}/attempts:batch",
        headers=headers,
        json=batch.model_dump(mode="json", by_alias=True),
    )
    second = client.post(
        f"/v1/runs/{run_id}/attempts:batch",
        headers=headers,
        json=batch.model_dump(mode="json", by_alias=True),
    )
    assert first.status_code == 200
    assert second.status_code == 200
    conflict = AttemptBatchRequest(
        items=[
            AttemptBatchItem(
                attempt_id=result.attempt_id,
                sequence=1,
                content_digest="0" * 64,
                result=result,
            )
        ]
    )
    third = client.post(
        f"/v1/runs/{run_id}/attempts:batch",
        headers=headers,
        json=conflict.model_dump(mode="json", by_alias=True),
    )
    assert third.status_code == 409


def test_complete_run_creates_finding_and_gate() -> None:
    client = _client()
    run_id = _register(client, "org-a-runner-token", "find-1")
    headers = {"Authorization": "Bearer org-a-runner-token"}
    client.post(f"/v1/runs/{run_id}/claim", headers=headers)
    pos = _attempt("POS-01", "PASS", "INVARIANT_HELD")
    ten = _attempt("TEN-01", "FAIL", "FORBIDDEN_RESOURCE_RETURNED")
    items = []
    for index, result in enumerate((pos, ten), start=1):
        payload = result.model_dump(mode="json", by_alias=True)
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        items.append(
            AttemptBatchItem(attempt_id=result.attempt_id, sequence=index, content_digest=digest, result=result)
        )
    client.post(
            f"/v1/runs/{run_id}/attempts:batch",
            headers=headers,
            json=AttemptBatchRequest(items=items).model_dump(mode="json", by_alias=True),
        )
    done = client.post(
        f"/v1/runs/{run_id}/complete",
        headers=headers,
        json=CompleteRunRequest(
            target_build="demo-support-local",
            expected_attempt_ids=[pos.attempt_id, ten.attempt_id],
        ).model_dump(mode="json"),
    )
    assert done.status_code == 200
    assert done.json()["gate"]["status"] == "blocked_finding"
    findings = client.get(
        f"/v1/projects/{PROJECT_A}/findings",
        headers={"Authorization": "Bearer org-a-viewer-token"},
    )
    assert findings.status_code == 200
    assert findings.json()[0]["case_id"] == "TEN-01"
    report = client.get(f"/v1/runs/{run_id}/report", headers={"Authorization": "Bearer org-a-viewer-token"})
    blob = json.dumps(report.json())
    assert "token-admin" not in blob
    assert "CANARY" not in blob
    html = client.get(
        f"/v1/runs/{run_id}/report?format=html",
        headers={"Authorization": "Bearer org-a-viewer-token"},
    )
    assert html.status_code == 200
    assert "text/html" in html.headers["content-type"]
    junit = client.get(
        f"/v1/runs/{run_id}/report?format=junit",
        headers={"Authorization": "Bearer org-a-viewer-token"},
    )
    assert junit.status_code == 200
    assert "<testsuite" in junit.text
    pdf = client.get(
        f"/v1/runs/{run_id}/report?format=pdf",
        headers={"Authorization": "Bearer org-a-viewer-token"},
    )
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")


def test_stale_lease_cannot_pass() -> None:
    engine = make_engine("sqlite://")
    factory = make_session_factory(engine)
    client = TestClient(create_app(engine, factory))
    run_id = _register(client, "org-a-runner-token", "stale-1")
    headers = {"Authorization": "Bearer org-a-runner-token"}
    client.post(f"/v1/runs/{run_id}/claim", headers=headers)
    with factory() as session:
        run = session.query(Run).filter_by(id=run_id).one()
        run.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.commit()
        reap_once(session, epoch=2)
        session.commit()
    complete = client.post(
        f"/v1/runs/{run_id}/complete",
        headers=headers,
        json=CompleteRunRequest(target_build="demo", expected_attempt_ids=[]).model_dump(mode="json"),
    )
    assert complete.status_code == 409
    shown = client.get(f"/v1/runs/{run_id}", headers=headers)
    assert shown.json()["execution_status"] == "Incomplete"
    assert shown.json()["gate"]["status"] == "blocked_incomplete"


def test_cancel_does_not_auto_pass() -> None:
    client = _client()
    run_id = _register(client, "org-a-runner-token", "cancel-1")
    client.post(f"/v1/runs/{run_id}/claim", headers={"Authorization": "Bearer org-a-runner-token"})
    cancelled = client.post(f"/v1/runs/{run_id}/cancel", headers={"Authorization": "Bearer org-a-editor-token"})
    assert cancelled.status_code == 200
    assert cancelled.json()["execution_status"] == "CancelRequested"
    assert cancelled.json()["gate"]["status"] != "satisfied"
    ack = client.post(
        f"/v1/runs/{run_id}/complete",
        headers={"Authorization": "Bearer org-a-runner-token"},
        json=CompleteRunRequest(target_build="demo", expected_attempt_ids=[]).model_dump(mode="json"),
    )
    assert ack.json()["execution_status"] == "Cancelled"
    assert ack.json()["gate"]["status"] == "blocked_incomplete"


def test_runner_cannot_use_other_org_environment() -> None:
    client = _client()
    response = client.post(
        "/v1/runs",
        headers={"Authorization": "Bearer org-a-runner-token"},
        json=CreateRunRequest(
            environment_id=ENV_B,
            suite_id="digest-support-v1",
            manifest=_manifest("cross-env"),
            idempotency_key="cross-env",
        ).model_dump(mode="json", by_alias=True),
    )
    assert response.status_code in {403, 404}
