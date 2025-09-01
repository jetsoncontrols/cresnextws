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
async def test_http_get_device_hostname(client):
    """Test HTTP GET request to retrieve device hostname."""

    # Test connection
    result = await client.connect()
    assert result is True
    assert client.connected is True

    try:
        # Make HTTP GET request to retrieve device hostname
        response = await client.http_get("/Device/Ethernet/HostName")
        
        # Verify we got a response
        assert response is not None
        
        # Check if we got a JSON response with the expected structure
        if isinstance(response, dict):
            # Expected structure: {"Device":{"Ethernet":{"HostName":"[value]"}}}
            assert "content" in response
            assert "Device" in response["content"]
            assert "Ethernet" in response["content"]["Device"]
            assert "HostName" in response["content"]["Device"]["Ethernet"]
            
            # Verify that the hostname value is a string
            hostname = response["content"]["Device"]["Ethernet"]["HostName"]
            assert isinstance(hostname, str)
            assert len(hostname) > 0  # Should not be empty
            
            print(f"Retrieved hostname: {hostname}")
        else:
            # If response is not JSON, it might be a different format
            # Check if it contains status/error information
            if "error" in response:
                pytest.skip(f"HTTP GET returned error: {response['error']}")
            else:
                pytest.fail(f"Unexpected response format: {type(response)} - {response}")
                
    finally:
        # Always disconnect
        await client.disconnect()
        assert client.connected is False



# @pytest.mark.integration
# @pytest.mark.asyncio
# async def test_send_command_when_connected(client):
#     """Test sending a command when connected."""
#     await client.connect()

#     response = await client.send_command("test_command", {"key": "value"})

#     assert response["status"] == "success"
#     assert response["command"] == "test_command"
#     assert response["data"] == {"key": "value"}

#     await client.disconnect()

# @pytest.mark.integration
# @pytest.mark.asyncio
# async def test_send_command_when_not_connected(client):
#     """Test that sending a command when not connected raises an error."""

#     with pytest.raises(
#         ConnectionError, match="Not connected to CresNext system"
#     ):
#         await client.send_command("test_command")


# @pytest.mark.integration
# @pytest.mark.asyncio
# async def test_async_context_manager(pytestconfig, client_config, credentials):
#     """Confirm the client works as an async context manager end-to-end."""
#     if not pytestconfig.getoption("--run-integration"):
#         pytest.skip("Integration tests are disabled. Use --run-integration to enable.")

#     async with CresNextWSClient(client_config) as c:
#         assert c.connected is True
#         resp = await c.send_command("ping")
#         assert resp["status"] == "success"

#     # After exiting the context manager the client should be disconnected
#     assert c.connected is False