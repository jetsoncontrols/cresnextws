"""
Basic tests for CresNextWSClient
"""

import pytest
from cresnextws import CresNextWSClient, ClientConfig


def test_client_initialization():
    """Test that CresNextWSClient can be initialized with basic config."""
    config = ClientConfig(host="test.local")
    client = CresNextWSClient(config)

    assert client.host == "test.local"
    assert client.port == 443
    assert client.ssl is True
    assert client.connected is False


def test_client_initialization_with_custom_params():
    """Test CresNextWSClient initialization with custom parameters via config."""
    config = ClientConfig(host="test.local", port=8080, ssl=False)
    client = CresNextWSClient(config)

    assert client.host == "test.local"
    assert client.port == 8080
    assert client.ssl is False
    assert client.connected is False


@pytest.mark.asyncio
async def test_client_connect_disconnect():
    """Test basic connect/disconnect functionality."""
    client = CresNextWSClient(ClientConfig(host="test.local"))

    # Test connection
    result = await client.connect()
    assert result is True
    assert client.connected is True

    # Test disconnection
    await client.disconnect()
    assert client.connected is False


@pytest.mark.asyncio
async def test_send_command_when_connected():
    """Test sending a command when connected."""
    client = CresNextWSClient(ClientConfig(host="test.local"))
    await client.connect()

    response = await client.send_command("test_command", {"key": "value"})

    assert response["status"] == "success"
    assert response["command"] == "test_command"
    assert response["data"] == {"key": "value"}

    await client.disconnect()


@pytest.mark.asyncio
async def test_send_command_when_not_connected():
    """Test that sending a command when not connected raises an error."""
    client = CresNextWSClient(ClientConfig(host="test.local"))

    with pytest.raises(
        ConnectionError, match="Not connected to CresNext system"
    ):
        await client.send_command("test_command")


@pytest.mark.asyncio
async def test_context_manager():
    """Test that the client works as an async context manager."""
    async with CresNextWSClient(ClientConfig(host="test.local")) as client:
        assert client.connected is True

        response = await client.send_command("test_command")
        assert response["status"] == "success"

    # Client should be disconnected after context manager exit
    assert client.connected is False


def test_client_config_initialization():
    """Test CresNextWSClient initialization with ClientConfig."""
    config = ClientConfig(host="test.local")
    client = CresNextWSClient(config)

    assert client.host == "test.local"
    assert client.port == 443
    assert client.ssl is True
    assert client.auto_reconnect is False
    assert client.connected is False


def test_client_config_initialization_with_custom_params():
    """Test CresNextWSClient initialization with custom ClientConfig."""
    config = ClientConfig(
        host="test.local", port=8080, ssl=False, auto_reconnect=True
    )
    client = CresNextWSClient(config)

    assert client.host == "test.local"
    assert client.port == 8080
    assert client.ssl is False
    assert client.auto_reconnect is True
    assert client.connected is False


def test_client_config_values_applied():
    """Test that values from config are applied correctly."""
    config = ClientConfig(host="test.local", port=8080, ssl=False)
    client = CresNextWSClient(config)

    assert client.host == "test.local"
    assert client.port == 8080
    assert client.ssl is False


# Note: Constructor now requires a config object; no backward compatibility for individual params.


@pytest.mark.asyncio
async def test_client_with_config_connect_disconnect():
    """Test basic connect/disconnect functionality with config."""
    config = ClientConfig(host="test.local", auto_reconnect=True)
    client = CresNextWSClient(config)

    # Test connection
    result = await client.connect()
    assert result is True
    assert client.connected is True

    # Test disconnection
    await client.disconnect()
    assert client.connected is False


@pytest.mark.asyncio
async def test_context_manager_with_config():
    """Test that the client works as an async context manager with config."""
    config = ClientConfig(host="test.local", auto_reconnect=True)
    async with CresNextWSClient(config) as client:
        assert client.connected is True
        assert client.auto_reconnect is True

        response = await client.send_command("test_command")
        assert response["status"] == "success"

    # Client should be disconnected after context manager exit
    assert client.connected is False


def test_client_config_with_custom_urls():
    """Test ClientConfig with custom URL endpoints."""
    config = ClientConfig(
        host="test.local",
        auth_path="/custom/auth/endpoint",
    websocket_path="/custom/ws/endpoint",
        ping_interval=15.0,
        reconnect_delay=2.5
    )
    client = CresNextWSClient(config)

    assert client.host == "test.local"
    assert client.auth_path == "/custom/auth/endpoint"
    assert client.websocket_path == "/custom/ws/endpoint"
    assert client.ping_interval == 15.0
    assert client.reconnect_delay == 2.5


def test_client_default_urls():
    """Test that default URL placeholders are set correctly from config defaults."""
    client = CresNextWSClient(ClientConfig(host="test.local"))

    assert client.auth_path == "/userlogin.html"
    assert client.websocket_path == "/websockify"
    assert client.ping_interval == 30.0
    assert client.reconnect_delay == 5.0


def test_client_config_with_urls():
    """Test that config URLs are applied correctly."""
    config = ClientConfig(
        host="test.local",
        port=8080,
        auth_path="/config/auth",
    websocket_path="/config/ws",
    )
    client = CresNextWSClient(config)

    assert client.host == "test.local"
    assert client.port == 8080
    assert client.auth_path == "/config/auth"
    assert client.websocket_path == "/config/ws"


@pytest.mark.asyncio
async def test_client_with_credentials():
    """Test that connect method accepts credentials."""
    client = CresNextWSClient(ClientConfig(host="test.local"))
    
    # Should connect successfully in test mode even with credentials
    result = await client.connect(username="testuser", password="testpass")
    assert result is True
    assert client.connected is True
    
    await client.disconnect()
    assert client.connected is False
