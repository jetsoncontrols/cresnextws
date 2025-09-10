#!/usr/bin/env python3
"""
Quick test script to verify the updated _process_message method handles nested data correctly.
"""

from unittest.mock import Mock
from cresnextws import CresNextWSClient, DataEventManager


def test_nested_message_processing():
    """Test that nested messages are processed correctly."""
    # Create mock client
    client = Mock(spec=CresNextWSClient)
    client.connected = True
    
    # Create data manager
    manager = DataEventManager(client)
    
    # Set up callbacks to track what gets called
    hostname_callback = Mock()
    device_callback = Mock()
    ethernet_callback = Mock()
    
    # Subscribe to different path patterns
    manager.subscribe("/Device/Ethernet/HostName", hostname_callback, match_children=False)
    manager.subscribe("/Device/Ethernet", ethernet_callback, match_children=True)  
    manager.subscribe("/Device", device_callback, match_children=True)
    
    # Test message in the format described
    test_message = {
        'Device': {
            'Ethernet': {
                'HostName': 'DM-NAX-4ZSP'
            }
        }
    }
    
    # Process the message
    manager._process_message(test_message)
    
    # Verify callbacks were called correctly
    print("Testing nested message processing...")
    print(f"Test message: {test_message}")
    print(f"Hostname callback called: {hostname_callback.called}")
    print(f"Ethernet callback called: {ethernet_callback.called}")
    print(f"Device callback called: {device_callback.called}")
    
    if hostname_callback.called:
        args, kwargs = hostname_callback.call_args
        print(f"Hostname callback args: {args}")
    
    if ethernet_callback.called:
        call_count = ethernet_callback.call_count
        print(f"Ethernet callback called {call_count} times")
        for i, call in enumerate(ethernet_callback.call_args_list):
            args, kwargs = call
            print(f"  Call {i+1}: {args}")
    
    if device_callback.called:
        call_count = device_callback.call_count
        print(f"Device callback called {call_count} times")
        for i, call in enumerate(device_callback.call_args_list):
            args, kwargs = call
            print(f"  Call {i+1}: {args}")
    
    # Assertions
    assert hostname_callback.called, "HostName callback should be called"
    assert ethernet_callback.called, "Ethernet callback should be called"
    assert device_callback.called, "Device callback should be called"
    
    # Check that hostname callback got the right data
    hostname_args = hostname_callback.call_args[0]
    assert hostname_args[0] == "/Device/Ethernet/HostName"
    assert hostname_args[1] == "DM-NAX-4ZSP"
    
    print("\n✅ All tests passed!")


if __name__ == "__main__":
    test_nested_message_processing()
