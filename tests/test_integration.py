"""
Optional integration tests that can run against one or more systems defined
in tests/services.json (or another file specified via --services-file).

Enable with: pytest --run-integration --systems all
or select specific systems: pytest --run-integration --systems local_sim
"""

import pytest
from cresnextws import CresNextWSClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_connect_and_basic_command(client):
    # 'client' fixture is provided by tests/conftest.py and yields a connected client
    assert client.connected is True

    # Minimal smoke command
    resp = await client.send_command("ping")
    assert resp["status"] == "success"

@pytest.mark.integration
@pytest.mark.asyncio
async def test_client_connect_disconnect(client):
    """Test basic connect/disconnect functionality."""

    # Test connection
    result = await client.connect()
    assert result is True
    assert client.connected is True

    # Test disconnection
    await client.disconnect()
    assert client.connected is False

@pytest.mark.integration
@pytest.mark.asyncio
async def test_send_command_when_connected(client):
    """Test sending a command when connected."""
    await client.connect()

    response = await client.send_command("test_command", {"key": "value"})

    assert response["status"] == "success"
    assert response["command"] == "test_command"
    assert response["data"] == {"key": "value"}

    await client.disconnect()

@pytest.mark.integration
@pytest.mark.asyncio
async def test_send_command_when_not_connected(client):
    """Test that sending a command when not connected raises an error."""

    with pytest.raises(
        ConnectionError, match="Not connected to CresNext system"
    ):
        await client.send_command("test_command")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_async_context_manager(pytestconfig, client_config, credentials):
    """Confirm the client works as an async context manager end-to-end."""
    if not pytestconfig.getoption("--run-integration"):
        pytest.skip("Integration tests are disabled. Use --run-integration to enable.")

    async with CresNextWSClient(client_config) as c:
        assert c.connected is True
        resp = await c.send_command("ping")
        assert resp["status"] == "success"

    # After exiting the context manager the client should be disconnected
    assert c.connected is False