"""
Example usage of the DataEventManager with CresNextWSClient

This example demonstrates how to:
1. Connect to a CresNext system
2. Set up a DataEventManager to monitor WebSocket messages
3. Subscribe to specific paths with callback functions
4. Process incoming data automatically
"""

import asyncio
import logging
from cresnextws import CresNextWSClient, ClientConfig, DataEventManager

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def device_config_callback(path: str, data):
    """Callback for device configuration changes."""
    print(f"Device config update - Path: {path}, Data: {data}")


def network_callback(path: str, data):
    """Callback for network-related changes.""" 
    print(f"Network update - Path: {path}, Data: {data}")


def all_data_callback(path: str, data):
    """Callback that receives all data updates."""
    print(f"All data - Path: {path}, Data: {data}")


async def main():
    """Main example function."""
    
    # Configure the client
    config = ClientConfig(
        host="192.168.1.100",  # Replace with your CresNext system IP
        username="admin",       # Replace with your username
        password="password"     # Replace with your password
    )
    
    # Create client and data event manager
    client = CresNextWSClient(config)
    data_manager = DataEventManager(client)
    
    try:
        # Connect to the system
        print("Connecting to CresNext system...")
        if not await client.connect():
            print("Failed to connect!")
            return
        
        print("Connected successfully!")
        
        # Set up subscriptions
        print("Setting up subscriptions...")
        
        # Subscribe to device configuration changes
        data_manager.subscribe(
            path_pattern="/Device/Config*",
            callback=device_config_callback,
            match_children=True
        )
        
        # Subscribe to network changes
        data_manager.subscribe(
            path_pattern="/Device/Network/*",
            callback=network_callback,
            match_children=True
        )
        
        # Subscribe to all data (for debugging)
        all_sub_id = data_manager.subscribe(
            path_pattern="*",
            callback=all_data_callback,
            match_children=True
        )
        
        print(f"Created {data_manager.subscription_count} subscriptions")
        
        # Start monitoring
        print("Starting message monitoring...")
        await data_manager.start_monitoring()
        
        # Request some data to trigger callbacks
        print("Requesting device information...")
        await client.ws_get("/Device/Config")
        await client.ws_get("/Device/Network/Interface")
        
        # Monitor for 30 seconds
        print("Monitoring for 30 seconds...")
        await asyncio.sleep(30)
        
        # Demonstrate unsubscribing
        print("Unsubscribing from all data callback...")
        data_manager.unsubscribe(all_sub_id)
        
        # Monitor for another 10 seconds
        print("Monitoring for 10 more seconds...")
        await asyncio.sleep(10)
        
    except KeyboardInterrupt:
        print("Interrupted by user")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Clean up
        print("Cleaning up...")
        await data_manager.stop_monitoring()
        await client.disconnect()
        print("Disconnected")


async def context_manager_example():
    """Example using async context managers."""
    
    config = ClientConfig(
        host="192.168.1.100",
        username="admin", 
        password="password"
    )
    
    # Using context managers for automatic cleanup
    async with CresNextWSClient(config) as client:
        async with DataEventManager(client) as data_manager:
            
            # Subscribe to data
            data_manager.subscribe(
                path_pattern="/Device/*",
                callback=lambda path, data: print(f"Data: {path} = {data}")
            )
            
            # Request some data
            await client.ws_get("/Device/Info")
            
            # Monitor for 10 seconds
            await asyncio.sleep(10)


if __name__ == "__main__":
    # Run the main example
    asyncio.run(main())
    
    # Uncomment to run the context manager example instead
    # asyncio.run(context_manager_example())
