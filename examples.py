#!/usr/bin/env python3
"""
Example usage of cresnextws library

This script demonstrates basic usage of the CresNextWSClient.
"""

import asyncio
import logging
from cresnextws import CresNextWSClient, ClientConfig


# Configure logging to see what's happening
logging.basicConfig(level=logging.INFO)


async def basic_example():
    """Basic usage example."""
    print("=== Basic Example ===")
    
    # Create a client instance
    client = CresNextWSClient(
        ClientConfig(
            host="example.cresnext.local",
            port=443,
            ssl=True,
            username="admin",
            password="password",
        )
    )
    
    # Connect to the system
    print(f"Connecting to {client.config.host}:{client.config.port}...")
    connected = await client.connect()
    
    if connected:
        print("✓ Connected successfully!")
        
        # Send some example commands
        try:
            response = await client.send_command("get_status")
            print(f"Status response: {response}")
            
            response = await client.send_command("set_volume", {"level": 50})
            print(f"Volume response: {response}")
            
        except Exception as e:
            print(f"Error sending command: {e}")
        
        # Disconnect
        await client.disconnect()
        print("✓ Disconnected")
    else:
        print("✗ Failed to connect")


async def context_manager_example():
    """Context manager usage example."""
    print("\n=== Context Manager Example ===")
    
    try:
        # Using async context manager for automatic connection management
        async with CresNextWSClient(
            ClientConfig(host="example.cresnext.local", username="admin", password="password")
        ) as client:
            print(f"✓ Auto-connected to {client.config.host}")
            
            # Send commands
            response = await client.send_command("get_info")
            print(f"Info response: {response}")
            
        print("✓ Auto-disconnected")
        
    except Exception as e:
        print(f"Error: {e}")


async def config_example():
    """Configuration object usage example."""
    print("\n=== Configuration Example ===")

    # Create a configuration object
    config = ClientConfig(
        host="example.cresnext.local",
        port=443,
        ssl=True,
        auto_reconnect=True,  # Enable automatic reconnection
        username="admin",
        password="password",
    )

    # Create a client instance using the config
    client = CresNextWSClient(config)

    # Connect to the system
    print(f"Connecting to {client.config.host}:{client.config.port}...")
    connected = await client.connect()

    if connected:
        print("✓ Connected successfully!")
        print(f"Auto-reconnect enabled: {client.config.auto_reconnect}")

        # Send some example commands
        try:
            response = await client.send_command("get_status")
            print(f"Status response: {response}")

            response = await client.send_command("set_volume", {"level": 50})
            print(f"Volume response: {response}")

        except Exception as e:
            print(f"Error sending command: {e}")

        # Disconnect
        await client.disconnect()
        print("✓ Disconnected")
    else:
        print("✗ Failed to connect")


async def http_get_example():
    """Example of using the HTTP GET functionality."""
    print("\n=== HTTP GET Example ===")
    
    # Create a client instance
    client = CresNextWSClient(
        ClientConfig(
            host="example.cresnext.local",
            username="admin",
            password="password",
        )
    )
    
    try:
        # Connect to the system
        print(f"Connecting to {client.config.host}...")
        connected = await client.connect()
        
        if connected:
            print("✓ Connected successfully!")
            
            # Example HTTP GET requests
            try:
                # Get system status
                print("Making HTTP GET request to /api/status...")
                response = await client.http_get("/api/status")
                if response:
                    print(f"Status response: {response}")
                
                # Get device information  
                print("Making HTTP GET request to /device/info...")
                response = await client.http_get("/device/info")
                if response:
                    print(f"Device info response: {response}")
                
                # Example of handling non-JSON response
                print("Making HTTP GET request to /version...")
                response = await client.http_get("/version")
                if response:
                    print(f"Version response: {response}")
                    
            except Exception as e:
                print(f"Error making HTTP request: {e}")
            
        else:
            print("✗ Connection failed")
            
    except Exception as e:
        print(f"Example error: {e}")
    finally:
        # Always disconnect
        if client.connected:
            await client.disconnect()
            print("✓ Disconnected")


async def main():
    """Run all examples."""
    print("CresNext WebSocket Client Examples")
    print("=" * 40)

    await basic_example()
    await config_example()
    await context_manager_example()
    await http_get_example()

    print("\n" + "=" * 40)
    print("Examples completed!")


if __name__ == "__main__":
    # Run the examples
    asyncio.run(main())