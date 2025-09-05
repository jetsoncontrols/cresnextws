"""
Basic tests for CresNextWSClient
"""

import pytest
from typing import Any
from cresnextws import CresNextWSClient, ClientConfig


def test_client_initialization():
    """Test that CresNextWSClient can be initialized with basic config."""
    config = ClientConfig(host="test.local", username="u", password="p")
    client = CresNextWSClient(config)

    assert client.config.host == "test.local"
    assert client.connected is False


def test_client_initialization_with_custom_params():
    """Test CresNextWSClient initialization with custom parameters via config."""
    config = ClientConfig(host="test.local", username="u", password="p")
    client = CresNextWSClient(config)

    assert client.config.host == "test.local"
    assert client.connected is False


def test_client_config_initialization():
    """Test CresNextWSClient initialization with ClientConfig."""
    config = ClientConfig(host="test.local", username="u", password="p")
    client = CresNextWSClient(config)

    assert client.config.host == "test.local"
    assert client.config.auto_reconnect is True
    assert client.connected is False


def test_client_config_with_custom_urls():
    """Test ClientConfig with custom URL endpoints."""
    config = ClientConfig(
        host="test.local",
        username="u",
        password="p",
        auth_path="/custom/auth/endpoint",
        websocket_path="/custom/ws/endpoint",
        ws_ping_interval=15.0,
        reconnect_delay=2.5
    )
    client = CresNextWSClient(config)

    assert client.config.host == "test.local"
    assert client.config.auth_path == "/custom/auth/endpoint"
    assert client.config.websocket_path == "/custom/ws/endpoint"
    assert client.config.ws_ping_interval == 15.0
    assert client.config.reconnect_delay == 2.5


def test_client_default_urls():
    """Test that default URL placeholders are set correctly from config defaults."""
    client = CresNextWSClient(ClientConfig(host="test.local", username="u", password="p"))

    assert client.config.auth_path == "/userlogin.html"
    assert client.config.websocket_path == "/websockify"
    assert client.config.ws_ping_interval == 10.0
    assert client.config.reconnect_delay == 5.0


@pytest.mark.asyncio
async def test_http_get_not_connected():
    """Test that http_get raises RuntimeError when not connected."""
    config = ClientConfig(host="test.local", username="u", password="p")
    client = CresNextWSClient(config)

    with pytest.raises(RuntimeError, match="Client is not connected"):
        await client.http_get("/test/path")


@pytest.mark.asyncio
async def test_http_put_not_connected():
    """Test that http_put raises RuntimeError when not connected."""
    config = ClientConfig(host="test.local", username="u", password="p")
    client = CresNextWSClient(config)

    with pytest.raises(RuntimeError, match="Client is not connected"):
        await client.http_post("/test/path", {"key": "value"})


@pytest.mark.asyncio
async def test_http_put_data_types():
    """Test that http_put validates data types correctly."""
    config = ClientConfig(host="test.local", username="u", password="p")
    client = CresNextWSClient(config)

    # Test unsupported data type - we need to bypass type checking for this test
    with pytest.raises(TypeError, match="Unsupported data type"):
        # Using Any to bypass type checking for test purposes
        invalid_data: Any = object()
        await client.http_post("/test/path", invalid_data)
