from __future__ import annotations

from urllib.parse import urlparse

import httpx

from assure_contracts.adapters import (
    ApprovedFixtureChange,
    ApprovedScope,
    AttemptContext,
    CleanupResult,
    ConversationResult,
    EvidenceEnvelope,
    Receipt,
    FixtureHandle,
    FixtureSpecRequest,
    FixtureState,
    ObservationCursor,
    PreflightResult,
    ScenarioRequest,
    StateSnapshot,
    TargetBuild,
)
from assure_contracts.config import AssureConfig


class PolicyError(ValueError):
    pass


class DemoAdapters:
    def __init__(self, config: AssureConfig, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)
        self._assert_local_alias(config.target.base_url)
        self._assert_local_alias(config.adapter.fixture_base_url)
        self._assert_local_alias(config.adapter.observation_base_url)

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    def _assert_local_alias(self, url: str) -> None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host not in {"127.0.0.1", "localhost", "demo", "support-demo"}:
            raise PolicyError(f"destination not in local execution policy: {url}")
        if parsed.scheme not in {"http", "https"}:
            raise PolicyError(f"unsupported scheme: {url}")
        if parsed.port not in {None, 80, 443, 8000, 8080}:
            raise PolicyError(f"port not permitted: {url}")

    def _admin_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.adapter.admin_token}"}

    def _user_headers(self, credential_ref: str) -> dict[str, str]:
        token = self.config.credentials.get(credential_ref)
        if not token:
            raise PolicyError(f"unknown credential_ref: {credential_ref}")
        if token.startswith("${"):
            raise PolicyError(f"unresolved credential: {credential_ref}")
        return {"Authorization": f"Bearer {token}"}

    async def identify_build(self) -> TargetBuild:
        response = await self.client.get(
            f"{self.config.adapter.fixture_base_url}/admin/build",
            headers=self._admin_headers(),
        )
        response.raise_for_status()
        return TargetBuild.model_validate(response.json())

    async def invoke(self, request: ScenarioRequest) -> ConversationResult:
        response = await self.client.post(
            f"{self.config.target.base_url}/v1/chat",
            headers=self._user_headers(request.credential_ref),
            json={
                "session_id": request.session_id,
                "message": request.input_text,
                "correlation_id": request.correlation_id,
                "max_turns": request.max_turns,
            },
        )
        response.raise_for_status()
        return ConversationResult.model_validate(response.json())

    async def preflight(self, scope: ApprovedScope) -> PreflightResult:
        response = await self.client.post(
            f"{self.config.adapter.fixture_base_url}/admin/preflight",
            headers=self._admin_headers(),
            json=scope.model_dump(),
        )
        response.raise_for_status()
        return PreflightResult.model_validate(response.json())

    async def prepare(self, spec: FixtureSpecRequest) -> FixtureHandle:
        response = await self.client.post(
            f"{self.config.adapter.fixture_base_url}/admin/fixtures/prepare",
            headers=self._admin_headers(),
            json=spec.model_dump(),
        )
        response.raise_for_status()
        return FixtureHandle.model_validate(response.json())

    async def verify(self, fixture: FixtureHandle) -> FixtureState:
        response = await self.client.post(
            f"{self.config.adapter.fixture_base_url}/admin/fixtures/verify",
            headers=self._admin_headers(),
            json=fixture.model_dump(),
        )
        response.raise_for_status()
        return FixtureState.model_validate(response.json())

    async def apply_test_change(self, change: ApprovedFixtureChange) -> Receipt:
        response = await self.client.post(
            f"{self.config.adapter.fixture_base_url}/admin/fixtures/change",
            headers=self._admin_headers(),
            json=change.model_dump(),
        )
        response.raise_for_status()
        return Receipt.model_validate(response.json())

    async def cleanup(self, fixture: FixtureHandle) -> CleanupResult:
        response = await self.client.post(
            f"{self.config.adapter.fixture_base_url}/admin/fixtures/cleanup",
            headers=self._admin_headers(),
            json=fixture.model_dump(),
        )
        response.raise_for_status()
        return CleanupResult.model_validate(response.json())

    async def begin(self, context: AttemptContext) -> ObservationCursor:
        response = await self.client.post(
            f"{self.config.adapter.observation_base_url}/admin/observations/begin",
            headers=self._admin_headers(),
            json=context.model_dump(),
        )
        response.raise_for_status()
        return ObservationCursor.model_validate(response.json())

    async def finish(self, cursor: ObservationCursor) -> EvidenceEnvelope:
        response = await self.client.post(
            f"{self.config.adapter.observation_base_url}/admin/observations/finish",
            headers=self._admin_headers(),
            json=cursor.model_dump(mode="json"),
        )
        response.raise_for_status()
        return EvidenceEnvelope.model_validate(response.json())

    async def snapshot(self, fixture: FixtureHandle) -> StateSnapshot:
        response = await self.client.get(
            f"{self.config.adapter.fixture_base_url}/admin/state/{fixture.namespace}",
            headers=self._admin_headers(),
        )
        response.raise_for_status()
        return StateSnapshot.model_validate(response.json())

    async def set_observer(self, enabled: bool) -> None:
        response = await self.client.post(
            f"{self.config.adapter.observation_base_url}/admin/observer",
            headers=self._admin_headers(),
            json={"enabled": enabled},
        )
        response.raise_for_status()
