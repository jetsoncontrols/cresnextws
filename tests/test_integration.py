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
            



@pytest.mark.integration
@pytest.mark.asyncio
async def test_http_post_update_hostname(client):
    """Test HTTP PUT to update device hostname and verify the change."""
    hostname_path = "/Device/Ethernet/HostName"
    
    # Step 1: Get the current hostname
    response = await client.http_get(hostname_path)
    assert response is not None
    assert "content" in response
    
    # Extract the current hostname
    if isinstance(response["content"], dict):
        # JSON response structure: {"Device":{"Ethernet":{"HostName":"[value]"}}}
        assert "Device" in response["content"]
        assert "Ethernet" in response["content"]["Device"]
        assert "HostName" in response["content"]["Device"]["Ethernet"]
        original_hostname = response["content"]["Device"]["Ethernet"]["HostName"]
    else:
        pytest.fail(f"Unexpected response content type: {type(response['content'])}")
    
    assert isinstance(original_hostname, str)
    assert len(original_hostname) > 0
    print(f"Original hostname: {original_hostname}")
    
    try:
        # Step 2: Create new hostname by appending "_test"
        new_hostname = f"{original_hostname}-test"
        print(f"New hostname: {new_hostname}")
        
        # Step 3: Update the hostname using HTTP PUT
        # Construct the full JSON structure for the PUT request
        json_data = {"Device": {"Ethernet": {"HostName": new_hostname}}}
        put_response = await client.http_post(hostname_path, json_data)
        assert put_response is not None            
        print(f"PUT response: {put_response}")
        
        # Step 4: Get the hostname again to verify the update
        verify_response = await client.http_get(hostname_path)
        assert verify_response is not None
        assert "content" in verify_response
        
        # Extract the updated hostname
        if isinstance(verify_response["content"], dict):
            # JSON response structure
            updated_hostname = verify_response["content"]["Device"]["Ethernet"]["HostName"]
        elif isinstance(verify_response["content"], str):
            # Plain text response
            updated_hostname = verify_response["content"]
        else:
            pytest.fail(f"Unexpected verify response content type: {type(verify_response['content'])}")
            
        print(f"Updated hostname: {updated_hostname}")
        
        # Step 5: Verify the hostname was updated correctly
        assert updated_hostname == new_hostname, f"Expected '{new_hostname}', got '{updated_hostname}'"
        
        print("✓ Hostname successfully updated and verified!")
        
    finally:
        # Step 6: Restore the original hostname
        print(f"Restoring original hostname: {original_hostname}")
        restore_json_data = {"Device": {"Ethernet": {"HostName": original_hostname}}}
        restore_response = await client.http_post(hostname_path, restore_json_data)
        print(f"Restore response: {restore_response}")
        
        # Verify restoration was successful
        final_response = await client.http_get(hostname_path)
        if final_response and "content" in final_response:
            if isinstance(final_response["content"], dict):
                final_hostname = final_response["content"]["Device"]["Ethernet"]["HostName"]
            elif isinstance(final_response["content"], str):
                final_hostname = final_response["content"]
            else:
                final_hostname = "unknown"
            
            if final_hostname == original_hostname:
                print("✓ Original hostname successfully restored!")
            else:
                print(f"⚠ Warning: Could not restore hostname. Expected '{original_hostname}', got '{final_hostname}'")
        else:
            print("⚠ Warning: Could not verify hostname restoration")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_send_command_when_not_connected():
    """Test that sending a command when not connected raises an error."""
    
    # Create a new client that is not connected
    from cresnextws import ClientConfig
    config = ClientConfig(host="test.local", username="test", password="test")
    disconnected_client = CresNextWSClient(config)
    
    # Ensure it's not connected
    assert disconnected_client.connected is False

    with pytest.raises(
        RuntimeError, match="Client is not connected"
    ):
        await disconnected_client.http_get("/Device")


