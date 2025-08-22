"""
Basic tests for CresNextWSClient
"""

from cresnextws import CresNextWSClient, ClientConfig


def test_client_initialization():
    """Test that CresNextWSClient can be initialized with basic config."""
    config = ClientConfig(host="test.local", username="u", password="p")
    client = CresNextWSClient(config)

    assert client.config.host == "test.local"
    assert client.config.port == 443
    assert client.config.ssl is True
    assert client.connected is False


def test_client_initialization_with_custom_params():
    """Test CresNextWSClient initialization with custom parameters via config."""
    config = ClientConfig(host="test.local", username="u", password="p", port=8080, ssl=False)
    client = CresNextWSClient(config)

    assert client.config.host == "test.local"
    assert client.config.port == 8080
    assert client.config.ssl is False
    assert client.connected is False


def test_client_config_initialization():
    """Test CresNextWSClient initialization with ClientConfig."""
    config = ClientConfig(host="test.local", username="u", password="p")
    client = CresNextWSClient(config)

    assert client.config.host == "test.local"
    assert client.config.port == 443
    assert client.config.ssl is True
    assert client.config.auto_reconnect is False
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
    assert client.config.ws_ping_interval == 30.0
    assert client.config.reconnect_delay == 5.0
