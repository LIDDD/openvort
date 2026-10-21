"""Exercise provider management against an isolated in-memory database."""

import json

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from openvort.contacts.models import Member
from openvort.db.models import VoiceProvider
from openvort.plugins.knowledge.models import KBChunk
from openvort.plugins.vortgit import crypto
from openvort.services.embedding import EmbeddingService


@pytest_asyncio.fixture
async def service(monkeypatch):
    monkeypatch.setattr(crypto, "_fernet", Fernet(Fernet.generate_key()))
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Member.__table__.create)
        await conn.run_sync(VoiceProvider.__table__.create)
    svc = EmbeddingService(async_sessionmaker(engine, expire_on_commit=False))
    yield svc
    await svc.close()
    await engine.dispose()


async def test_crud_masks_key_preserves_key_and_inherits_default(service):
    first = await service.add_provider(
        name="First", platform="dashscope", api_key="test-secret-key",
        config={"model": "text-embedding-v3", "dimensions": 1024},
    )
    assert first.is_default
    assert first.api_key != "test-secret-key"
    second = await service.add_provider(name="Second", platform="dashscope", api_key="second-key")
    rows = await service.list_providers()
    assert len(rows) == 2
    assert "test-secret-key" not in json.dumps(rows)
    assert rows[0]["api_key_masked"] == "tes***key"
    edited = await service.update_provider(provider_id=first.id, name="Renamed")
    assert service._decrypt_secret(edited.api_key) == "test-secret-key"
    assert await service.delete_provider(first.id)
    rows = await service.list_providers()
    assert rows[0]["id"] == second.id and rows[0]["is_default"]
    assert service.available and service.dimensions == 1024
    assert not await service.delete_provider("missing-id")


@pytest.mark.parametrize("dimensions", [512, 1536, 0, -1, "512", None])
async def test_reject_dimensions_incompatible_with_knowledge_table(service, dimensions):
    with pytest.raises(ValueError, match="1024"):
        await service.add_provider(
            name="Invalid dimensions", platform="dashscope",
            config={"dimensions": dimensions},
        )


async def test_update_rejects_incompatible_dimensions(service):
    provider = await service.add_provider(name="Valid", platform="dashscope")
    with pytest.raises(ValueError, match="1024"):
        await service.update_provider(provider_id=provider.id, config={"dimensions": 512})
    assert service.dimensions == 1024


async def test_encryption_failure_does_not_store_plaintext(service, monkeypatch):
    def fail_encrypt(value):
        raise RuntimeError("Synthetic encryption failure")

    monkeypatch.setattr(crypto, "encrypt_token", fail_encrypt)
    with pytest.raises(RuntimeError, match="encryption failure"):
        await service.add_provider(name="Secret", platform="dashscope", api_key="test-secret-key")
    assert await service.list_providers() == []


async def test_embedding_vectors_match_the_knowledge_storage(service, monkeypatch):
    await service.add_provider(name="Knowledge", platform="dashscope")
    provider = service._get_provider()

    async def fake_batch(texts):
        return [[0.0] * provider.dimensions for _ in texts]

    monkeypatch.setattr(provider, "_embed_batch", fake_batch)
    vectors = await service.embed(["Synthetic document"])
    serialize = KBChunk.__table__.c.embedding.type.bind_processor(postgresql.dialect())
    assert serialize(vectors[0])
    with pytest.raises(ValueError, match="expected 1024 dimensions, not 512"):
        serialize([0.0] * 512)


async def test_admin_routes_crud_and_singleton_reload(service, monkeypatch):
    import openvort.web.app as web_app
    from openvort.web.routers import embedding_providers

    monkeypatch.setattr(web_app, "_setup_mcp", lambda app: None)
    monkeypatch.setattr(
        web_app, "verify_token", lambda token: {"sub": "test-user", "roles": [token]},
    )
    monkeypatch.setattr(embedding_providers, "get_db_session_factory", lambda: service._session_factory)
    monkeypatch.setattr(embedding_providers, "get_embedding_service", lambda: service)
    app = web_app.create_app()
    url = "/api/admin/embedding-providers"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(url)).status_code == 401
        assert (await client.get(url, headers={"Authorization": "Bearer member"})).status_code == 403
        client.headers["Authorization"] = "Bearer admin"
        response = await client.post(url, json={
            "name": "API test", "platform": "dashscope", "api_key": "test-api-key",
            "config": {"dimensions": 1024},
        })
        assert response.status_code == 200, response.text
        provider_id = response.json()["id"]
        assert service.available
        listed = await client.get(url)
        assert listed.status_code == 200
        assert len(listed.json()["providers"]) == 1
        assert "test-api-key" not in listed.text
        rejected = await client.put(f"{url}/{provider_id}", json={"config": {"dimensions": 512}})
        assert rejected.status_code == 400 and "1024" in rejected.text
        edited = await client.put(f"{url}/{provider_id}", json={"name": "Renamed"})
        assert edited.status_code == 200
        assert (await client.delete(f"{url}/{provider_id}")).status_code == 200
        assert not service.available
