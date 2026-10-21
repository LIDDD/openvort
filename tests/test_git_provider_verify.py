"""Verify the self-hosted URL is forwarded without making network requests."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from openvort.plugins.vortgit.tools.providers import ManageProviderTool


@pytest.mark.parametrize("api_base", ["https://gitlab.example.test/api/v4", ""])
async def test_verify_uses_provider_api_base(api_base):
    provider = SimpleNamespace(
        id="test-provider", name="Test GitLab", platform="gitlab",
        access_token="encrypted-test-token", api_base=api_base,
    )
    session = AsyncMock()
    session.get.return_value = provider
    context = AsyncMock()
    context.__aenter__.return_value = session
    factory = Mock(return_value=context)
    client = AsyncMock()
    client.list_repos.return_value = [{"full_name": "test/repository"}]
    with (
        patch("openvort.db.engine.get_session_factory", return_value=factory),
        patch("openvort.plugins.vortgit.crypto.decrypt_token", return_value="test-token"),
        patch("openvort.plugins.vortgit.providers.create_provider", return_value=client) as create,
    ):
        result = json.loads(await ManageProviderTool()._verify({"provider_id": provider.id}))
    assert result["ok"] is True
    create.assert_called_once_with("gitlab", access_token="test-token", api_base=api_base)
    client.close.assert_awaited_once()
