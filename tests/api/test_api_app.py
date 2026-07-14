from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from sec_insider_db.api.app import create_app
from sec_insider_db.api.deps import get_session
from sec_insider_db.api.settings import ApiSettings


class DummySession:
    async def execute(self, *_args, **_kwargs):
        raise AssertionError("DB should not be called in this test")


@pytest.fixture
def app():
    return create_app(
        ApiSettings(
            database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/sec_insider_db",
            frontend_enabled=True,
        )
    )


@pytest.mark.anyio
async def test_openapi_contains_expected_operation_ids(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    operation_ids = {
        operation["operationId"]
        for path in response.json()["paths"].values()
        for operation in path.values()
    }
    assert "get_api_health" in operation_ids
    assert "list_cluster_buys" in operation_ids
    assert "search_transactions" in operation_ids


@pytest.mark.anyio
async def test_frontend_index_served(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert 'class="site-brand"' in response.text
    assert "Insider DB" in response.text
    assert '<a href="#/sales">Sales</a>' in response.text
    assert 'brand-mark">SEC</span>' not in response.text


@pytest.mark.anyio
async def test_frontend_sales_page_assets_are_served(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/assets/app.js?v=198766")

    assert response.status_code == 200
    assert "async function salesPage()" in response.text
    assert "params.set('transaction_code', 'S')" in response.text
    assert "params.set('offset', String(offset))" in response.text
    assert "if (parts[0] === 'sales') return await salesPage()" in response.text
    assert "offset = 0" in response.text
    assert "offset = Math.max(0, offset - limit)" in response.text
    assert "offset += limit" in response.text
    assert "rows.length < limit ? 'disabled' : ''" in response.text
    assert "No sales found" in response.text
    assert "Sales request failed" in response.text


@pytest.mark.anyio
async def test_health_uses_dependency_override(app):
    async def override_session():
        class Session:
            async def execute(self, *_args, **_kwargs):
                return None
        yield Session()

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.anyio
async def test_limit_validation_happens_before_database_dependency(app):
    async def override_session():
        yield DummySession()

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/transactions?limit=999")

    assert response.status_code == 422
