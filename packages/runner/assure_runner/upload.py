from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from assure_contracts.api import AttemptBatchItem, AttemptBatchRequest, CompleteRunRequest, CreateRunRequest
from assure_contracts.config import AssureConfig
from assure_contracts.manifest import RunManifest
from assure_contracts.result import AttemptResult, RunSummary


async def upload_results(config: AssureConfig, manifest_path: Path, summary_path: Path) -> dict:
    if not config.control_plane.runner_token:
        raise ValueError("control_plane.runner_token is required for upload")
    manifest = RunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    summary = RunSummary.model_validate_json(summary_path.read_text(encoding="utf-8"))
    if config.control_plane.environment_id:
        manifest = manifest.model_copy(update={"environment_id": config.control_plane.environment_id})
    if config.control_plane.project_id:
        manifest = manifest.model_copy(update={"project_id": config.control_plane.project_id})

    headers = {"Authorization": f"Bearer {config.control_plane.runner_token}"}
    base = config.control_plane.base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        created = await client.post(
            f"{base}/v1/runs",
            headers=headers,
            json=CreateRunRequest(
                environment_id=manifest.environment_id or config.control_plane.environment_id,
                suite_id=manifest.suite_digest,
                manifest=manifest,
                idempotency_key=f"upload-{manifest.run_id}",
            ).model_dump(mode="json", by_alias=True),
        )
        created.raise_for_status()
        run = created.json()
        run_id = run["id"]
        claim = await client.post(f"{base}/v1/runs/{run_id}/claim", headers=headers)
        claim.raise_for_status()
        items = []
        for index, attempt in enumerate(summary.attempts, start=1):
            payload = attempt.model_dump(mode="json", by_alias=True)
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            items.append(
                AttemptBatchItem(
                    attempt_id=attempt.attempt_id,
                    sequence=index,
                    content_digest=digest,
                    result=AttemptResult.model_validate(payload),
                )
            )
        batch = await client.post(
            f"{base}/v1/runs/{run_id}/attempts:batch",
            headers=headers,
            json=AttemptBatchRequest(items=items).model_dump(mode="json", by_alias=True),
        )
        batch.raise_for_status()
        complete = await client.post(
            f"{base}/v1/runs/{run_id}/complete",
            headers=headers,
            json=CompleteRunRequest(
                target_build=summary.target_build,
                expected_attempt_ids=[item.attempt_id for item in summary.attempts],
                cleanup_ok=summary.cleanup_ok,
            ).model_dump(mode="json"),
        )
        complete.raise_for_status()
        return complete.json()
