from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from assure_adapters.http import DemoAdapters
from assure_contracts.config import AssureConfig
from assure_demo.app import create_app
from assure_demo.store import DemoStore


def make_config() -> AssureConfig:
    return AssureConfig.model_validate(
        {
            "schema": "assure/config/v1",
            "target": {"alias": "support_staging", "base_url": "http://127.0.0.1:8080"},
            "credentials": {
                "tenant_a_reader": "token-a-reader",
                "tenant_a_editor": "token-a-editor",
                "tenant_b_reader": "token-b-reader",
                "tenant_b_editor": "token-b-editor",
            },
            "adapter": {
                "admin_token": "token-admin",
                "fixture_base_url": "http://127.0.0.1:8080",
                "observation_base_url": "http://127.0.0.1:8080",
            },
        }
    )


@pytest.fixture
def suite_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "suites" / "support_v1"


@pytest_asyncio.fixture
async def demo_env():
    store = DemoStore()
    app = create_app(store)
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8080")
    adapters = DemoAdapters(make_config(), client=client)
    try:
        yield store, adapters
    finally:
        await adapters.aclose()
