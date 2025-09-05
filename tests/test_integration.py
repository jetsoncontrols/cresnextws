"""
Optional integration tests that can run against one or more systems defined
in tests/services.json (or another file specified via --services-file).

Enable with: pytest -m integration --run-integration --systems all
or select specific systems: pytest --run-integration --systems local_sim

pytest -m integration --run-integration --systems oakforest_4zsp tests/test_integration.py::test_ws_get_device_model -vs
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
async def test_ws_get_device_model(client):
    """Test WebSocket GET request to retrieve device model name via ws_get method."""
    import asyncio
    
    # Send a WebSocket GET request for the model name
    await client.ws_get("/Device/DeviceInfo/Model")
    print("WebSocket GET request sent for /Device/DeviceInfo/Model")
    
    # Listen for the response on the WebSocket
    # We'll wait up to 10 seconds for a response
    timeout_seconds = 10
    start_time = asyncio.get_event_loop().time()
    
    response_received = False
    model_response = None
    
    while not response_received and (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
        try:
            # Wait for the next message with a short timeout
            message = await client.next_message(timeout=1.0)
            
            if message is not None:
                print(f"Received WebSocket message: {message}")
                
                # Check if this message contains the model response
                # Expected structure: {"Device":{"DeviceInfo":{"Model":"[value]"}}}
                if (isinstance(message, dict) and 
                    "Device" in message and 
                    isinstance(message["Device"], dict) and
                    "DeviceInfo" in message["Device"] and
                    isinstance(message["Device"]["DeviceInfo"], dict) and
                    "Model" in message["Device"]["DeviceInfo"]):
                    model_response = message
                    response_received = True
                    break
                    
        except asyncio.TimeoutError:
            # No message received in this 1-second window, continue waiting
            continue
        except Exception as e:
            pytest.fail(f"Error receiving WebSocket message: {e}")
    
    # Verify we received the expected response
    assert response_received, f"No model response received via WebSocket within {timeout_seconds} seconds"
    assert model_response is not None, "Model response should not be None"
    
    # Verify the response structure and content
    assert "Device" in model_response
    assert "DeviceInfo" in model_response["Device"]
    assert "Model" in model_response["Device"]["DeviceInfo"]
    
    # Verify that the model value is a string and not empty
    model = model_response["Device"]["DeviceInfo"]["Model"]
    assert isinstance(model, str), f"Model should be a string, got {type(model)}"
    assert len(model) > 0, "Model should not be empty"
    
    print(f"✓ Successfully received model via WebSocket: {model}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ws_post_hostname_change_and_verify(client):
    """Test WebSocket POST to change hostname and verify via WebSocket reception."""
    import asyncio
    
    hostname_path = "/Device/Ethernet/HostName"
    
    # Step 1: Get the current hostname via HTTP first
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
        # Step 2: Create new hostname by appending "_wstest"
        new_hostname = f"{original_hostname}-wstest"
        print(f"New hostname: {new_hostname}")
        
        # Step 3: Subscribe to hostname changes via WebSocket first
        await client.ws_get(hostname_path)
        print("WebSocket GET request sent to subscribe to hostname changes")
        
        # Clear any pending messages in the queue before making the change
        timeout_seconds = 2
        start_time = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
            try:
                message = await client.next_message(timeout=0.5)
                if message is not None:
                    print(f"Cleared pending message: {message}")
            except asyncio.TimeoutError:
                break
        
        # Step 4: Update the hostname using WebSocket POST
        hostname_payload = {"Device": {"Ethernet": {"HostName": new_hostname}}}
        await client.ws_post(hostname_payload)
        print(f"WebSocket POST request sent with new hostname: {new_hostname}")
        
        # Step 5: Wait for the hostname change notification via WebSocket
        timeout_seconds = 15
        start_time = asyncio.get_event_loop().time()
        
        hostname_change_received = False
        received_hostname = None
        
        while not hostname_change_received and (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
            try:
                # Wait for the next message with a short timeout
                message = await client.next_message(timeout=1.0)
                
                if message is not None:
                    print(f"Received WebSocket message: {message}")
                    
                    # Check if this message contains the hostname response
                    # Expected structure: {"Device":{"Ethernet":{"HostName":"[value]"}}}
                    if (isinstance(message, dict) and 
                        "Device" in message and 
                        isinstance(message["Device"], dict) and
                        "Ethernet" in message["Device"] and
                        isinstance(message["Device"]["Ethernet"], dict) and
                        "HostName" in message["Device"]["Ethernet"]):
                        
                        received_hostname = message["Device"]["Ethernet"]["HostName"]
                        hostname_change_received = True
                        break
                        
            except asyncio.TimeoutError:
                # No message received in this 1-second window, continue waiting
                continue
            except Exception as e:
                pytest.fail(f"Error receiving WebSocket message: {e}")
        
        # Step 6: Verify we received the expected hostname change
        assert hostname_change_received, f"No hostname change received via WebSocket within {timeout_seconds} seconds"
        assert received_hostname is not None, "Received hostname should not be None"
        assert received_hostname == new_hostname, f"Expected hostname '{new_hostname}', got '{received_hostname}'"
        
        print(f"✓ Successfully verified hostname change via WebSocket: {received_hostname}")
        
    finally:
        # Step 7: Restore the original hostname using WebSocket POST
        print(f"Restoring original hostname: {original_hostname}")
        restore_payload = {"Device": {"Ethernet": {"HostName": original_hostname}}}
        await client.ws_post(restore_payload)
        
        # Wait for restoration confirmation via WebSocket
        timeout_seconds = 10
        start_time = asyncio.get_event_loop().time()
        
        restore_confirmed = False
        
        while not restore_confirmed and (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
            try:
                message = await client.next_message(timeout=1.0)
                
                if message is not None:
                    print(f"Received restoration message: {message}")
                    
                    # Check if this message contains the restored hostname
                    if (isinstance(message, dict) and 
                        "Device" in message and 
                        isinstance(message["Device"], dict) and
                        "Ethernet" in message["Device"] and
                        isinstance(message["Device"]["Ethernet"], dict) and
                        "HostName" in message["Device"]["Ethernet"]):
                        
                        restored_hostname = message["Device"]["Ethernet"]["HostName"]
                        if restored_hostname == original_hostname:
                            restore_confirmed = True
                            print(f"✓ Original hostname successfully restored via WebSocket: {restored_hostname}")
                            break
                        
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"⚠ Warning: Error during hostname restoration verification: {e}")
                break
        
        if not restore_confirmed:
            print("⚠ Warning: Could not confirm hostname restoration via WebSocket")


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
        
    # Also test that ws_get raises an error when not connected
    with pytest.raises(
        RuntimeError, match="WebSocket is not connected"
    ):
        await disconnected_client.ws_get("/Device/Ethernet/HostName")
    
    # Also test that ws_post raises an error when not connected
    with pytest.raises(
        RuntimeError, match="WebSocket is not connected"
    ):
        await disconnected_client.ws_post({"test": "data"})


