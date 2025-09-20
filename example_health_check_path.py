#!/usr/bin/env python3
"""
Example demonstrating the health check path feature.

This example shows how to configure the health check to make real API calls
during health checks for enhanced connection validation.
"""

import asyncio
from cresnextws import CresNextWSClient, ClientConfig, ConnectionStatus


async def health_check_path_example():
    """Demonstrate health check with WebSocket GET path validation."""
    print("=== Health Check Path Example ===")
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
    """Run the health check path example."""
    await health_check_path_example()


if __name__ == "__main__":
    asyncio.run(main())