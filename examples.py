#!/usr/bin/env python3
"""
Example usage of cresnextws library

This script demonstrates comprehensive usage of the CresNextWSClient and DataEventManager.
Examples are based on real usage patterns found in the test suite (see tests/ directory).

Includes examples for:
- Basic HTTP/WebSocket operations
- Configuration management
- Health check configuration for connection reliability
- Health check with enhanced path validation
- Context manager usage
- DataEventManager with various subscription patterns
- DataEventManager full_message option (new feature)
- DataEventManager as context manager (auto-cleanup)
- DataEventManager auto-restart functionality
- Manual restart control for DataEventManager
- Device monitoring with specialized callbacks
- WebSocket message handling
- Advanced batch operations

Run with: python3 examples.py

Note: Examples use placeholder hostnames. Update the host/credentials for your system.
"""

import asyncio
import logging
from cresnextws import CresNextWSClient, ClientConfig, DataEventManager, ConnectionStatus


# Configure logging to see what's happening
logging.basicConfig(level=logging.INFO)


async def basic_example():
    """Basic usage example with HTTP and WebSocket operations."""
    print("=== Basic Example ===")
    
    # Create a client instance
    client = CresNextWSClient(
        ClientConfig(
            host="example.cresnext.local",
            username="admin",
            password="password",
        )
    )
    
    # Connect to the system
    print(f"Connecting to {client.config.host}...")
    connected = await client.connect()
    
    if connected:
        print("✓ Connected successfully!")
        
        try:
            # HTTP GET example - retrieve device hostname
            print("\n--- HTTP Operations ---")
            response = await client.http_get("/Device/Ethernet/HostName")
            print(f"Hostname response: {response}")
            
            # HTTP GET example - retrieve device model
            response = await client.http_get("/Device/DeviceInfo/Model")
            print(f"Model response: {response}")
            
            # HTTP POST example - update a configuration value
            # Note: This modifies the system, so we restore it afterwards
            original_hostname = None
            if response and "content" in response:
                original_hostname = response["content"]["Device"]["Ethernet"]["HostName"]
                
                # Update hostname temporarily
                new_data = {"Device": {"Ethernet": {"HostName": f"{original_hostname}-test"}}}
                update_response = await client.http_post("/Device/Ethernet/HostName", new_data)
                print(f"Update response: {update_response}")
                
                # Restore original hostname
                restore_data = {"Device": {"Ethernet": {"HostName": original_hostname}}}
                await client.http_post("/Device/Ethernet/HostName", restore_data)
                print("✓ Hostname restored")
            
            # WebSocket operations
            print("\n--- WebSocket Operations ---")
            
            # WebSocket GET - request current device model
            await client.ws_get("/Device/DeviceInfo/Model")
            print("WebSocket GET request sent for device model")
            
            # Wait for and receive the response
            ws_response = await client.next_message(timeout=5.0)
            if ws_response:
                print(f"WebSocket response: {ws_response}")
            else:
                print("No WebSocket response received within timeout")
                
        except Exception as e:
            print(f"Error during operations: {e}")
        
        # Disconnect
        await client.disconnect()
        print("✓ Disconnected")
    else:
        print("✗ Failed to connect")


async def connection_status_events_example():
    """
    Example demonstrating connection status event subscription.
    
    This example shows how external applications can monitor the CresNext client's
    connection status and respond to connect/disconnect events.
    """
    print("\n=== Connection Status Events Example ===")
    
    def on_connection_status_change(status: ConnectionStatus):
        """
        Callback function that gets called whenever the connection status changes.
        
        Args:
            status: The new ConnectionStatus
        """
        if status == ConnectionStatus.CONNECTED:
            print("🟢 Client connected successfully!")
        elif status == ConnectionStatus.DISCONNECTED:
            print("🔴 Client disconnected")
        elif status == ConnectionStatus.CONNECTING:
            print("🟡 Client connecting...")
        elif status == ConnectionStatus.RECONNECTING_FIRST:
            print("🔄 First reconnect attempt (usually succeeds quickly)")
        elif status == ConnectionStatus.RECONNECTING:
            print("🟠 Client reconnecting (connection issues detected)...")

    # Create client configuration
    config = ClientConfig(
        host="example.cresnext.local",  # Replace with your device
        username="admin",
        password="password",
        auto_reconnect=True,
        reconnect_delay=2.0
    )
    
    # Create client
    client = CresNextWSClient(config)
    
    # Subscribe to connection status events
    print("Adding connection status event handler...")
    client.add_connection_status_handler(on_connection_status_change)
    
    # Show current status
    print(f"Initial status: {client.get_connection_status().value}")
    
    try:
        # Connect to the device
        print("Starting connection...")
        success = await client.connect()
        
        if success:
            print("Connection established, waiting for events...")
            
            # Wait for some time to observe events
            await asyncio.sleep(3)
            
            # Manually disconnect to demonstrate disconnect event
            print("Manually disconnecting...")
            await client.disconnect()
            
        else:
            print("Connection failed (expected with example hostname)")
            
    except KeyboardInterrupt:
        print("Interrupted by user")
    except Exception as e:
        print(f"Connection error (expected): {e}")
    finally:
        # Clean up
        if client.connected:
            await client.disconnect()
        
        # Remove the handler (optional, but good practice)
        print("Removing connection status event handler...")
        client.remove_connection_status_handler(on_connection_status_change)


async def context_manager_example():
    """Context manager usage example with automatic cleanup."""
    print("\n=== Context Manager Example ===")
    
    try:
        # Using async context manager for automatic connection management
        async with CresNextWSClient(
            ClientConfig(host="example.cresnext.local", username="admin", password="password")
        ) as client:
            print(f"✓ Auto-connected to {client.config.host}")
            
            # Send multiple requests efficiently
            tasks = [
                client.http_get("/Device/Ethernet/HostName"),
                client.http_get("/Device/DeviceInfo/Model"),
                client.http_get("/Device/DeviceInfo/SerialNumber"),
            ]
            
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, response in enumerate(responses):
                if isinstance(response, Exception):
                    print(f"Request {i+1} failed: {response}")
                else:
                    print(f"Request {i+1} response: {response}")
            
        print("✓ Auto-disconnected")
        
    except Exception as e:
        print(f"Error: {e}")


async def config_example():
    """Configuration object usage example with custom settings."""
    print("\n=== Configuration Example ===")
    
    # Create config with custom settings
    config = ClientConfig(
        host="example.cresnext.local",
        username="admin", 
        password="password",
        auto_reconnect=True,
        reconnect_delay=2.0,
        auth_path="/userlogin.html",
        websocket_path="/websockify"
    )
    
    print(f"Host: {config.host}")
    print(f"Auto-reconnect: {config.auto_reconnect}")
    print(f"Reconnect delay: {config.reconnect_delay}s")
    print(f"Auth endpoint: {config.auth_path}")
    print(f"WebSocket endpoint: {config.websocket_path}")
    
    # Create client and demonstrate utility methods
    client = CresNextWSClient(config)
    
    # Get the base endpoint URL
    base_url = client.get_base_endpoint()
    print(f"Base HTTPS endpoint: {base_url}")
    print("This base URL is used for all HTTP requests and WebSocket origins.")


async def health_check_example():
    """Health check configuration example for connection reliability."""
    print("\n=== Health Check Example ===")
    print("Demonstrates automatic health monitoring and reconnection after system sleep/wake.")
    
    config = ClientConfig(
        host="example.cresnext.local",
        username="admin",
        password="password",
        auto_reconnect=True,            # Required for health check
        health_check_interval=10.0,     # Check every 10 seconds (faster for demo)
        health_check_timeout=3.0,       # 3 second timeout
        health_check_path="/Device/DeviceInfo/Model"  # Optional: real API call for enhanced validation
    )
    
    def on_status_change(status: ConnectionStatus):
        """Monitor connection status changes."""
        timestamp = asyncio.get_event_loop().time()
        print(f"[{timestamp:.1f}] Connection status: {status}")
        
        if status == ConnectionStatus.RECONNECTING:
            print("  -> Health check detected stale connection, reconnecting...")
    
    client = CresNextWSClient(config)
    client.add_connection_status_handler(on_status_change)
    
    try:
        print("Connecting with health check enabled...")
        await client.connect()
        print("✓ Connected")
        
        print(f"Health check will ping every {config.health_check_interval} seconds")
        if config.health_check_path:
            print(f"Health check will also send WebSocket GET to: {config.health_check_path}")
            print("This provides enhanced validation by making real API calls to the device")
        print("The health check runs in the background and will detect stale connections")
        print("(e.g., after system sleep/wake cycles)")
        
        print("\nMonitoring for 30 seconds...")
        print("If you put your computer to sleep and wake it up during this time,")
        print("you should see the health check detect and reconnect the stale connection.")
        
        # Monitor for 30 seconds to demonstrate health check
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < 30:
            await asyncio.sleep(1)
            if not client.connected:
                print("Connection lost, waiting for reconnection...")
                # Wait a bit for reconnection
                await asyncio.sleep(5)
        
        print("✓ Health check monitoring completed")
        
    except Exception as e:
        print(f"Health check example error: {e}")
    finally:
        client.remove_connection_status_handler(on_status_change)
        await client.disconnect()
        print("✓ Disconnected")


async def data_event_manager_example():
    """Data Event Manager example with subscriptions and callbacks."""
    print("\n=== Data Event Manager Example ===")
    
    config = ClientConfig(
        host="example.cresnext.local",
        username="admin",
        password="password"
    )
    
    client = CresNextWSClient(config)
    data_manager = DataEventManager(client)
    
    # Storage for received events
    received_events = []
    
    def hostname_callback(path: str, data):
        """Callback for hostname changes."""
        print(f"Hostname event - Path: {path}, Data: {data}")
        received_events.append({"type": "hostname", "path": path, "data": data})
    
    def device_info_callback(path: str, data):
        """Callback for device info changes."""
        print(f"Device info event - Path: {path}, Data: {data}")
        received_events.append({"type": "device_info", "path": path, "data": data})
    
    def all_data_callback(path: str, data):
        """Callback for all data changes (for monitoring)."""
        print(f"All data event - Path: {path}")
        received_events.append({"type": "all", "path": path, "data": data})
    
    try:
        # Connect to the system
        print("Connecting...")
        if not await client.connect():
            print("Failed to connect!")
            return
        
        print("✓ Connected successfully!")
        
        # Set up subscriptions
        print("\nSetting up subscriptions...")
        
        # Subscribe to hostname changes
        hostname_sub_id = data_manager.subscribe(
            path_pattern="/Device/Ethernet/HostName",
            callback=hostname_callback,
            match_children=False
        )
        
        # Subscribe to all device info changes
        device_info_sub_id = data_manager.subscribe(
            path_pattern="/Device/DeviceInfo/*",
            callback=device_info_callback,
            match_children=True
        )
        
        # Subscribe to everything for monitoring (optional)
        all_sub_id = data_manager.subscribe(
            path_pattern="*",
            callback=all_data_callback,
            match_children=True
        )
        
        print(f"Created {len(data_manager._subscriptions)} subscriptions")
        print(f"Subscription IDs: {hostname_sub_id}, {device_info_sub_id}, {all_sub_id}")
        
        # Start monitoring WebSocket messages
        print("Starting message monitoring...")
        await data_manager.start_monitoring()
        
        # Request some data to trigger callbacks
        print("\nRequesting data...")
        await client.ws_get("/Device/Ethernet/HostName")
        await client.ws_get("/Device/DeviceInfo/Model")
        await client.ws_get("/Device/DeviceInfo/SerialNumber")
        
        # Wait for events to be processed
        print("Waiting for events...")
        await asyncio.sleep(5)
        
        # Show subscription info
        print(f"\nReceived {len(received_events)} events total")
        for event in received_events[:3]:  # Show first 3 events
            print(f"  {event['type']}: {event['path']}")
        
        # Demonstrate unsubscribing
        print("\nUnsubscribing from all-data monitor...")
        data_manager.unsubscribe(all_sub_id)
        
        # Clear events and test again
        received_events.clear()
        await client.ws_get("/Device/Ethernet/HostName")
        await asyncio.sleep(2)
        
        print(f"After unsubscribing, received {len(received_events)} events")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Clean up
        print("Cleaning up...")
        await data_manager.stop_monitoring()
        await client.disconnect()
        print("✓ Cleaned up and disconnected")


async def full_message_example():
    """Example demonstrating the full_message option in DataEventManager subscriptions."""
    print("\n=== Full Message Example ===")
    
    config = ClientConfig(
        host="example.cresnext.local",
        username="admin",  
        password="password",
        ignore_self_signed=True
    )
    
    client = CresNextWSClient(config)
    data_manager = DataEventManager(client)
    
    # Storage for received events
    received_events = []
    
    def value_only_callback(path: str, data):
        """Callback that receives only the changed value (default behavior)."""
        print(f"Value-only callback - Path: {path}")
        print(f"  Data type: {type(data)}")
        print(f"  Data: {data}")
        received_events.append({"type": "value_only", "path": path, "data": data})
    
    def full_message_callback(path: str, data):
        """Callback that receives the full JSON message."""
        print(f"Full-message callback - Path: {path}")
        print(f"  Data type: {type(data)}")
        print(f"  Data keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
        received_events.append({"type": "full_message", "path": path, "data": data})
    
    try:
        # Connect to the system
        print("Connecting...")
        if not await client.connect():
            print("Failed to connect!")
            return
        
        print("✓ Connected successfully!")
        
        # Set up subscriptions with different full_message settings
        print("\nSetting up subscriptions...")
        
        # Traditional subscription (full_message=False by default)
        value_sub_id = data_manager.subscribe(
            path_pattern="/Device/Ethernet/HostName",
            callback=value_only_callback,
            match_children=False,
            full_message=False  # Explicit for clarity, this is the default
        )
        
        # New full-message subscription
        full_sub_id = data_manager.subscribe(
            path_pattern="/Device/Ethernet/HostName", 
            callback=full_message_callback,
            match_children=False,
            full_message=True  # This is the new functionality
        )
        
        print(f"Created subscriptions: value-only ({value_sub_id}) and full-message ({full_sub_id})")
        
        # Display subscription info
        subscriptions = data_manager.get_subscriptions()
        print("\nSubscription details:")
        for sub in subscriptions:
            print(f"  ID: {sub['subscription_id']}")
            print(f"  Pattern: {sub['path_pattern']}")  
            print(f"  Full message: {sub['full_message']}")
            print()
        
        # Start monitoring WebSocket messages
        print("Starting message monitoring...")
        await data_manager.start_monitoring()
        
        # Request data to trigger both callbacks
        print("\nRequesting hostname data...")
        await client.ws_get("/Device/Ethernet/HostName")
        
        # Wait for events to be processed
        print("Waiting for events...")
        await asyncio.sleep(3)
        
        # Show the difference between the callbacks
        print(f"\nReceived {len(received_events)} events total")
        for event in received_events:
            print(f"\nEvent type: {event['type']}")
            print(f"  Path: {event['path']}")
            if event['type'] == 'value_only':
                print(f"  Received only the value: {event['data']}")
            else:  # full_message
                print(f"  Received full message with keys: {list(event['data'].keys()) if isinstance(event['data'], dict) else 'N/A'}")
                print(f"  Full message: {event['data']}")
        
        # Demonstrate mixed usage - one path with both subscription types
        print("\n--- Mixed Subscription Demo ---")
        print("Both callbacks will be triggered for the same data change:")
        print("- Value-only callback will receive just the changed value")
        print("- Full-message callback will receive the entire WebSocket message")
        
        received_events.clear()
        await client.ws_get("/Device/Ethernet/HostName") 
        await asyncio.sleep(2)
        
        print(f"\nAfter second request, received {len(received_events)} events")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Clean up
        print("\nCleaning up...")
        await data_manager.stop_monitoring()
        await client.disconnect()
        print("✓ Cleaned up and disconnected")


async def websocket_message_handling_example():
    """Example showing manual WebSocket message handling."""
    print("\n=== WebSocket Message Handling Example ===")
    
    config = ClientConfig(
        host="example.cresnext.local",
        username="admin",
        password="password"
    )
    
    try:
        async with CresNextWSClient(config) as client:
            print("✓ Connected")
            
            # Send multiple WebSocket requests
            await client.ws_get("/Device/Ethernet/HostName")
            await client.ws_get("/Device/DeviceInfo/Model")
            
            # Manually handle incoming messages
            print("Waiting for WebSocket messages...")
            for i in range(3):  # Wait for up to 3 messages
                try:
                    message = await client.next_message(timeout=3.0)
                    if message:
                        print(f"Message {i+1}: {message}")
                    else:
                        print(f"No message {i+1} received")
                        break
                except asyncio.TimeoutError:
                    print(f"Timeout waiting for message {i+1}")
                    break
                    
    except Exception as e:
        print(f"Error: {e}")


async def advanced_operations_example():
    """Advanced operations example showing common device management tasks."""
    print("\n=== Advanced Operations Example ===")
    
    config = ClientConfig(
        host="example.cresnext.local",
        username="admin",
        password="password"
    )
    
    try:
        async with CresNextWSClient(config) as client:
            print("✓ Connected")
            
            # Common device information queries
            print("\n--- Device Information ---")
            device_queries = [
                "/Device/DeviceInfo/Model",
                "/Device/DeviceInfo/SerialNumber", 
                "/Device/DeviceInfo/FirmwareVersion",
                "/Device/Ethernet/HostName",
                "/Device/Ethernet/IPAddress",
                "/Device/Ethernet/MACAddress"
            ]
            
            for query in device_queries:
                try:
                    response = await client.http_get(query)
                    if response and "content" in response:
                        # Extract the value from the nested response
                        content = response["content"]
                        print(f"{query}: {content}")
                    else:
                        print(f"{query}: No data received")
                except Exception as e:
                    print(f"{query}: Error - {e}")
                    
            # WebSocket subscription pattern for real-time monitoring
            print("\n--- Real-time Monitoring via WebSocket ---")
            
            # Subscribe to changes first
            await client.ws_get("/Device/Ethernet/HostName")
            await client.ws_get("/Device/DeviceInfo/Model")
            
            # Process any immediate responses
            for i in range(2):
                try:
                    message = await client.next_message(timeout=2.0)
                    if message:
                        print(f"Monitored data: {message}")
                except asyncio.TimeoutError:
                    print("No more immediate responses")
                    break
                    
    except Exception as e:
        print(f"Error: {e}")


async def batch_operations_example():
    """Example showing efficient batch operations."""
    print("\n=== Batch Operations Example ===")
    
    config = ClientConfig(
        host="example.cresnext.local",
        username="admin", 
        password="password"
    )
    
    try:
        async with CresNextWSClient(config) as client:
            print("✓ Connected")
            
            # Batch HTTP GET requests
            print("\n--- Batch HTTP Requests ---")
            batch_paths = [
                "/Device/Ethernet/HostName",
                "/Device/DeviceInfo/Model", 
                "/Device/DeviceInfo/SerialNumber",
                "/Device/Ethernet/IPAddress"
            ]
            
            # Send all requests concurrently
            tasks = [client.http_get(path) for path in batch_paths]
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for path, response in zip(batch_paths, responses):
                if isinstance(response, Exception):
                    print(f"{path}: Error - {response}")
                elif response and isinstance(response, dict) and "content" in response:
                    print(f"{path}: {response['content']}")
                else:
                    print(f"{path}: No content received")
                    
            # Batch WebSocket subscriptions
            print("\n--- Batch WebSocket Subscriptions ---")
            ws_paths = [
                "/Device/Ethernet",
                "/Device/DeviceInfo",
                "/Device/Network"
            ]
            
            # Subscribe to multiple paths
            for path in ws_paths:
                await client.ws_get(path)
                print(f"Subscribed to: {path}")
                
            # Collect responses
            print("Collecting WebSocket responses...")
            responses_collected = 0
            while responses_collected < len(ws_paths):
                try:
                    message = await client.next_message(timeout=3.0)
                    if message:
                        print(f"Response {responses_collected + 1}: {type(message)} data")
                        responses_collected += 1
                    else:
                        break
                except asyncio.TimeoutError:
                    print("Timeout waiting for more responses")
                    break
                    
    except Exception as e:
        print(f"Error: {e}")


async def data_event_manager_context_example():
    """DataEventManager context manager example with automatic cleanup."""
    print("\n=== DataEventManager Context Manager Example ===")
    
    config = ClientConfig(
        host="example.cresnext.local",
        username="admin", 
        password="password"
    )
    
    try:
        # Using nested context managers for automatic cleanup
        async with CresNextWSClient(config) as client:
            async with DataEventManager(client) as data_manager:
                print("✓ Connected with auto-managed DataEventManager")
                
                # Subscribe to device data with lambda callback
                data_manager.subscribe(
                    path_pattern="/Device/*",
                    callback=lambda path, data: print(f"Data: {path} = {data}"),
                    match_children=True
                )
                
                # Subscribe to specific network interfaces
                data_manager.subscribe(
                    path_pattern="/Device/Network/Interface*",
                    callback=lambda path, data: print(f"Network interface: {path}"),
                    match_children=True
                )
                
                print(f"Created {data_manager.subscription_count} subscriptions")
                
                # Request some data to trigger callbacks
                await client.ws_get("/Device/Info")
                await client.ws_get("/Device/Network/Interface")
                
                # Monitor for a short period
                print("Monitoring for 5 seconds...")
                await asyncio.sleep(5)
                
        print("✓ Auto-disconnected and cleaned up DataEventManager")
                
    except Exception as e:
        print(f"Error: {e}")


async def device_monitoring_example():
    """Enhanced device monitoring example with config and network subscriptions."""
    print("\n=== Device Monitoring Example ===")
    
    config = ClientConfig(
        host="example.cresnext.local",
        username="admin",
        password="password"
    )
    
    client = CresNextWSClient(config)
    data_manager = DataEventManager(client)
    
    # Define specialized callback functions
    def device_config_callback(path: str, data):
        """Callback for device configuration changes."""
        print(f"🔧 Device config update - Path: {path}")
        if data:
            print(f"   Data: {data}")

    def network_callback(path: str, data):
        """Callback for network-related changes.""" 
        print(f"🌐 Network update - Path: {path}")
        if data:
            print(f"   Data: {data}")

    def all_data_callback(path: str, data):
        """Callback that receives all data updates (for debugging)."""
        print(f"📊 All data - Path: {path}")
    
    try:
        # Connect to the system
        print("Connecting to CresNext system...")
        if not await client.connect():
            print("Failed to connect!")
            return
        
        print("✓ Connected successfully!")
        
        # Set up specialized subscriptions
        print("Setting up specialized subscriptions...")
        
        # Subscribe to device configuration changes (broader pattern)
        config_sub_id = data_manager.subscribe(
            path_pattern="/Device/Config*",
            callback=device_config_callback,
            match_children=True
        )
        
        # Subscribe to network changes (specific pattern)
        network_sub_id = data_manager.subscribe(
            path_pattern="/Device/Network/*",
            callback=network_callback,
            match_children=True
        )
        
        # Subscribe to all data for debugging (optional)
        all_sub_id = data_manager.subscribe(
            path_pattern="*",
            callback=all_data_callback,
            match_children=True
        )
        
        print(f"✓ Created {data_manager.subscription_count} subscriptions")
        print(f"   Subscription IDs: {config_sub_id}, {network_sub_id}, {all_sub_id}")
        
        # Start monitoring
        print("Starting message monitoring...")
        await data_manager.start_monitoring()
        
        # Request device information to trigger callbacks
        print("\nRequesting device information...")
        await client.ws_get("/Device/Config")
        await client.ws_get("/Device/Network/Interface")
        await client.ws_get("/Device/DeviceInfo/Model")
        
        # Monitor for 15 seconds
        print("Monitoring for 15 seconds...")
        try:
            await asyncio.sleep(15)
        except KeyboardInterrupt:
            print("\n⚠️  Monitoring interrupted by user")
        
        # Demonstrate selective unsubscribing
        print("\nUnsubscribing from debug callback...")
        data_manager.unsubscribe(all_sub_id)
        print(f"Now have {data_manager.subscription_count} active subscriptions")
        
        # Continue monitoring for a bit more
        print("Monitoring for 5 more seconds...")
        try:
            await client.ws_get("/Device/Config")  # Trigger another event
            await asyncio.sleep(5)
        except KeyboardInterrupt:
            print("\n⚠️  Final monitoring interrupted by user")
        
    except KeyboardInterrupt:
        print("\n⚠️  Example interrupted by user")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        # Clean up
        print("\nCleaning up...")
        await data_manager.stop_monitoring()
        await client.disconnect()
        print("✓ Disconnected and cleaned up")


async def auto_restart_example():
    """
    Demonstrate automatic monitoring restart on reconnection.
    """
    print("\n=== DataEventManager Auto-Restart Example ===")
    print("This example shows how monitoring automatically restarts after reconnection")
    print()

    def on_device_data(path: str, data):
        """Callback for device data changes."""
        print(f"📊 Device data changed: {path} = {data}")

    def on_connection_status(status: ConnectionStatus):
        """Callback to monitor connection status changes."""
        if status == ConnectionStatus.CONNECTED:
            print("🟢 Client connected!")
        elif status == ConnectionStatus.DISCONNECTED:
            print("🔴 Client disconnected!")
        elif status == ConnectionStatus.CONNECTING:
            print("🟡 Client connecting...")
        elif status == ConnectionStatus.RECONNECTING_FIRST:
            print("� First reconnect attempt...")
        elif status == ConnectionStatus.RECONNECTING:
            print("�🟠 Client reconnecting (multiple attempts)...")

    # Create client with auto-reconnect enabled
    client = CresNextWSClient(
        ClientConfig(
            host="example.cresnext.local",  # Update with your device hostname
            username="admin",
            password="password",
            auto_reconnect=True,
            reconnect_delay=1.0,  # Quick reconnect for demo
            max_reconnect_delay=5.0,
        )
    )

    # Add connection status handler to see what's happening
    client.add_connection_status_handler(on_connection_status)

    # Create DataEventManager - monitoring will always restart after reconnection
    data_manager = DataEventManager(client)

    try:
        # Connect to the system
        print(f"Connecting to {client.config.host}...")
        if not await client.connect():
            print("❌ Failed to connect to the system")
            return

        # Set up some subscriptions
        print("\n📋 Setting up data subscriptions...")
        sub1 = data_manager.subscribe("/Device/Info/*", on_device_data)
        sub2 = data_manager.subscribe("/Device/Network/*", on_device_data)
        print(f"Created subscriptions: {sub1}, {sub2}")

        # Start monitoring
        print("\n🎯 Starting message monitoring...")
        await data_manager.start_monitoring()
        print(f"Monitoring status: {data_manager.is_monitoring}")
        print("Auto-restart always enabled - monitoring will restart after reconnection")

        # Request some initial data
        print("\n📡 Requesting device information...")
        await client.ws_get("/Device/Info")
        await client.ws_get("/Device/Network/Interface")

        # Monitor for a while
        print("\n👀 Monitoring for messages (30 seconds)...")
        print("💡 Try disconnecting/reconnecting the device or network to see auto-restart in action")
        
        for i in range(30):
            await asyncio.sleep(1)
            
            # Show status every 5 seconds
            if i % 5 == 0:
                status = client.get_connection_status()
                monitoring = data_manager.is_monitoring
                print(f"⏰ {i+1}s - Status: {status.value}, Monitoring: {monitoring}")

        print("\n✅ Example completed successfully")
        
    except KeyboardInterrupt:
        print("\n⏹️  Example interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        # Clean up
        print("\n🧹 Cleaning up...")
        await data_manager.stop_monitoring()
        data_manager.cleanup()  # Remove connection status handler
        await client.disconnect()


async def manual_restart_example():
    """
    Demonstrate manual control over monitoring restart.
    """
    print("\n=== Manual Restart Control Example ===")
    print("This example shows how to disable auto-restart and manually control monitoring")
    print()

    def on_device_data(path: str, data):
        """Callback for device data changes."""
        print(f"📊 Device data changed: {path} = {data}")

    client = CresNextWSClient(
        ClientConfig(
            host="example.cresnext.local",
            username="admin", 
            password="password",
            auto_reconnect=True,
        )
    )

    # Create DataEventManager - monitoring will always restart after reconnection
    data_manager = DataEventManager(client)

    # Add our own connection status handler for manual control
    def manual_connection_handler(status: ConnectionStatus):
        print(f"🔧 Manual handler - Connection status: {status.value}")
        
        if status == ConnectionStatus.CONNECTED:
            if not data_manager.is_monitoring:
                print("🔧 Manually restarting monitoring...")
                # Create task for async operation since handler must be sync
                async def restart_monitoring():
                    try:
                        await data_manager.start_monitoring()
                        print("🔧 Monitoring restarted successfully")
                    except Exception as e:
                        print(f"🔧 Failed to restart monitoring: {e}")
                
                asyncio.create_task(restart_monitoring())

    client.add_connection_status_handler(manual_connection_handler)

    try:
        print(f"Connecting to {client.config.host}...")
        if not await client.connect():
            print("❌ Failed to connect")
            return

        data_manager.subscribe("/Device/*", on_device_data)
        await data_manager.start_monitoring()

        print("Auto-restart always enabled - monitoring will restart after reconnection")
        print("Monitor for connection changes (15 seconds)...")
        
        await asyncio.sleep(15)

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await data_manager.stop_monitoring()
        data_manager.cleanup()
        await client.disconnect()


async def auto_restart_context_manager_example():
    """
    Demonstrate using DataEventManager as context manager with auto-restart.
    """
    print("\n=== Context Manager with Auto-Restart Example ===")
    print()

    def on_device_data(path: str, data):
        """Callback for device data changes."""
        print(f"📊 Device data changed: {path} = {data}")

    def on_connection_status(status: ConnectionStatus):
        """Callback to monitor connection status changes."""
        if status == ConnectionStatus.CONNECTED:
            print("🟢 Client connected!")
        elif status == ConnectionStatus.DISCONNECTED:
            print("🔴 Client disconnected!")
        elif status == ConnectionStatus.CONNECTING:
            print("🟡 Client connecting...")
        elif status == ConnectionStatus.RECONNECTING:
            print("🟠 Client reconnecting...")

    client = CresNextWSClient(
        ClientConfig(
            host="example.cresnext.local",
            username="admin",
            password="password",
            auto_reconnect=True,
        )
    )

    client.add_connection_status_handler(on_connection_status)

    try:
        await client.connect()
        
        # Using as context manager automatically starts monitoring and cleans up
        async with DataEventManager(client) as data_manager:
            print(f"✨ Context manager started monitoring: {data_manager.is_monitoring}")
            
            data_manager.subscribe("/Device/SystemInfo/*", on_device_data)
            await client.ws_get("/Device/SystemInfo")
            
            print("Monitoring in context for 10 seconds...")
            await asyncio.sleep(10)
            
        # Monitoring is automatically stopped and cleaned up here
        print("✨ Context manager automatically cleaned up")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await client.disconnect()


async def health_check_path_example():
    """Demonstrate health check with WebSocket GET path validation."""
    print("\n=== Health Check Path Example ===")
    print("Demonstrates enhanced health checking with real API calls")
    
    # Configure with health check path for enhanced validation
    config = ClientConfig(
        host="example.cresnext.local",
        username="admin",
        password="password",
        auto_reconnect=True,
        health_check_interval=10.0,     # Check every 10 seconds
        health_check_timeout=3.0,       # 3 second timeout
        health_check_path="/Device/DeviceInfo/Model"  # Real API call for validation
    )
    
    def on_status_change(status: ConnectionStatus):
        """Monitor connection status changes."""
        timestamp = asyncio.get_event_loop().time()
        print(f"[{timestamp:.1f}] Connection status: {status}")
        
        if status == ConnectionStatus.RECONNECTING:
            print("  -> Health check detected stale connection, reconnecting...")
    
    client = CresNextWSClient(config)
    client.add_connection_status_handler(on_status_change)
    
    try:
        print("Connecting with enhanced health check...")
        await client.connect()
        print("✓ Connected")
        
        print("Health check configuration:")
        print(f"  - Ping interval: {config.health_check_interval} seconds")
        print(f"  - Ping timeout: {config.health_check_timeout} seconds")
        print(f"  - Enhanced path: {config.health_check_path}")
        print()
        print("The health check will:")
        print("1. Send WebSocket ping/pong for basic connectivity")
        print("2. Send WebSocket GET to the configured path for real API validation")
        print("This provides more robust detection of connection issues")
        print()
        
        print("Monitoring for 30 seconds...")
        print("You can simulate connection issues to see the enhanced health check in action")
        
        # Monitor for 30 seconds to demonstrate health check
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < 30:
            await asyncio.sleep(1)
            if not client.connected:
                print("Connection lost, waiting for reconnection...")
                await asyncio.sleep(5)
        
        print("✓ Enhanced health check monitoring completed")
        
    except Exception as e:
        print(f"Health check path example error: {e}")
    finally:
        client.remove_connection_status_handler(on_status_change)
        await client.disconnect()
        print("✓ Disconnected")


async def main():
    """Run all examples."""
    print("CresNext WebSocket Client Examples")
    print("=" * 50)

    await basic_example()
    await connection_status_events_example()
    await config_example()
    await health_check_example()
    await health_check_path_example()
    await context_manager_example()
    await data_event_manager_example()
    await full_message_example()
    await data_event_manager_context_example()
    await device_monitoring_example()
    await auto_restart_example()
    await manual_restart_example()
    await auto_restart_context_manager_example()
    await websocket_message_handling_example()
    await advanced_operations_example()
    await batch_operations_example()

    print("\n" + "=" * 50)
    print("Examples completed!")
    print("\nFor integration testing with real devices, see:")
    print("  pytest -m integration --run-integration --systems <system_name>")


if __name__ == "__main__":
    # Run the examples
    asyncio.run(main())