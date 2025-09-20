#!/usr/bin/env python3
"""
Example demonstrating DataEventManager auto-restart functionality

This example shows how the DataEventManager can automatically restart monitoring
when the client reconnects after a disconnection. This is useful for scenarios
where network connectivity is temporarily lost or the device needs to be restarted.
"""

import asyncio
import logging
from cresnextws import CresNextWSClient, ClientConfig, DataEventManager, ConnectionStatus


# Configure logging to see connection status changes
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


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


async def auto_restart_example():
    """
    Demonstrate automatic monitoring restart on reconnection.
    """
    print("=== DataEventManager Auto-Restart Example ===")
    print("This example shows how monitoring automatically restarts after reconnection")
    print()

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

    # Create DataEventManager with auto-restart enabled (default)
    data_manager = DataEventManager(client, auto_restart_monitoring=True)

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
        print(f"Auto-restart enabled: {data_manager.auto_restart_monitoring}")

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
    print("=== Manual Restart Control Example ===")
    print("This example shows how to disable auto-restart and manually control monitoring")
    print()

    client = CresNextWSClient(
        ClientConfig(
            host="example.cresnext.local",
            username="admin", 
            password="password",
            auto_reconnect=True,
        )
    )

    # Create DataEventManager with auto-restart DISABLED
    data_manager = DataEventManager(client, auto_restart_monitoring=False)

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

        print(f"Auto-restart disabled: {not data_manager.auto_restart_monitoring}")
        print("Monitor for connection changes (15 seconds)...")
        
        await asyncio.sleep(15)

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await data_manager.stop_monitoring()
        data_manager.cleanup()
        await client.disconnect()


async def context_manager_example():
    """
    Demonstrate using DataEventManager as context manager with auto-restart.
    """
    print("=== Context Manager with Auto-Restart Example ===")
    print()

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
        async with DataEventManager(client, auto_restart_monitoring=True) as data_manager:
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


async def main():
    """Run all examples."""
    examples = [
        ("Auto-Restart Example", auto_restart_example),
        ("Manual Restart Example", manual_restart_example), 
        ("Context Manager Example", context_manager_example),
    ]

    for name, example_func in examples:
        try:
            await example_func()
        except Exception as e:
            print(f"❌ {name} failed: {e}")
        
        print("\n" + "="*60 + "\n")
        await asyncio.sleep(1)  # Brief pause between examples


if __name__ == "__main__":
    print("🚀 CresNext DataEventManager Auto-Restart Examples")
    print("Update the hostname and credentials in the examples before running")
    print("="*60)
    
    asyncio.run(main())