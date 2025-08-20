"""
Basic tests for CresNextWSClient
"""

import pytest
from cresnextws import CresNextWSClient


def test_client_initialization():
    """Test that CresNextWSClient can be initialized with basic parameters."""
    client = CresNextWSClient(host="test.local")
    
    assert client.host == "test.local"
    assert client.port == 443
    assert client.ssl is True
    assert client.connected is False


def test_client_initialization_with_custom_params():
    """Test CresNextWSClient initialization with custom parameters."""
    client = CresNextWSClient(host="test.local", port=8080, ssl=False)
    
    assert client.host == "test.local"
    assert client.port == 8080
    assert client.ssl is False
    assert client.connected is False


@pytest.mark.asyncio
async def test_client_connect_disconnect():
    """Test basic connect/disconnect functionality."""
    client = CresNextWSClient(host="test.local")
    
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
    client = CresNextWSClient(host="test.local")
    await client.connect()
    
    response = await client.send_command("test_command", {"key": "value"})
    
    assert response["status"] == "success"
    assert response["command"] == "test_command"
    assert response["data"] == {"key": "value"}
    
    await client.disconnect()


@pytest.mark.asyncio
async def test_send_command_when_not_connected():
    """Test that sending a command when not connected raises an error."""
    client = CresNextWSClient(host="test.local")
    
    with pytest.raises(ConnectionError, match="Not connected to CresNext system"):
        await client.send_command("test_command")


@pytest.mark.asyncio
async def test_context_manager():
    """Test that the client works as an async context manager."""
    async with CresNextWSClient(host="test.local") as client:
        assert client.connected is True
        
        response = await client.send_command("test_command")
        assert response["status"] == "success"
    
    # Client should be disconnected after context manager exit
    assert client.connected is False